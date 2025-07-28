import asyncio
import time
import json
from pathlib import Path
from typing import Dict, List
import docker
from tinydb import TinyDB, Query
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from utils.logger import get_logger
from utils.webhook import WebhookNotifier

class GitWatcher(FileSystemEventHandler):
    def __init__(self, monitor):
        self.monitor = monitor
        self.logger = get_logger('git_watcher')

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.git/HEAD'):
            return
        
        bot_name = Path(event.src_path).parent.parent.name
        asyncio.create_task(self.monitor.handle_git_update(bot_name))

class BotMonitor:
    def __init__(self):
        self.db = TinyDB('data/t10.db')
        self.bots_table = self.db.table('bots')
        self.logger = get_logger('monitor')
        self.docker_client = docker.from_env()
        self.webhook = WebhookNotifier()
        self.running = False
        self.nitrix_monitor_active = False
        
    async def start_monitoring(self):
        """Start the monitoring loop"""
        self.running = True
        self.nitrix_monitor_active = True
        self.logger.info("Starting Nitrix bot monitoring system")
        
        self._setup_git_watchers()
        
        tasks = [
            self._monitor_bot_health(),
            self._monitor_crashes(),
            self._cleanup_dead_containers()
        ]
        
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            self.logger.error(f"Monitor error: {e}")
        finally:
            self.running = False
            self.nitrix_monitor_active = False

    async def _monitor_bot_health(self):
        """Monitor bot health and restart if needed"""
        while self.running:
            try:
                Bot = Query()
                running_bots = self.bots_table.search(Bot.status == 'running')
                
                for bot_record in running_bots:
                    bot_name = bot_record['name']
                    config = bot_record.get('config', {})
                    
                    if not await self._is_container_healthy(bot_name):
                        self.logger.warning(f"Bot {bot_name} appears unhealthy")
                        
                        if config.get('restart_on_crash', True):
                            await self._handle_bot_crash(bot_name, config)
                
                await asyncio.sleep(30)
                
            except Exception as e:
                self.logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(60)

    async def _monitor_crashes(self):
        """Monitor for crashed containers"""
        while self.running:
            try:
                containers = self.docker_client.containers.list(
                    all=True,
                    filters={'name': 't10_'}
                )
                
                for container in containers:
                    if container.status in ['exited', 'dead']:
                        bot_name = container.name.replace('t10_', '')
                        await self._handle_container_crash(bot_name, container)
                
                await asyncio.sleep(15)
                
            except Exception as e:
                self.logger.error(f"Crash monitoring error: {e}")
                await asyncio.sleep(30)

    async def _cleanup_dead_containers(self):
        """Clean up dead containers periodically"""
        while self.running:
            try:
                containers = self.docker_client.containers.list(
                    all=True,
                    filters={'status': 'exited', 'name': 't10_'}
                )
                
                for container in containers:
                    if container.status == 'exited':
                        try:
                            container.remove()
                            self.logger.info(f"Cleaned up container: {container.name}")
                        except Exception as e:
                            self.logger.error(f"Failed to cleanup container {container.name}: {e}")
                
                await asyncio.sleep(300)  # Clean up every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(300)

    async def _is_container_healthy(self, bot_name: str) -> bool:
        """Check if a bot container is healthy"""
        try:
            container_name = f"t10_{bot_name}"
            container = self.docker_client.containers.get(container_name)
            
            if container.status != 'running':
                return False
            
            # Check if container is responsive
            try:
                stats = container.stats(stream=False)
                return True
            except:
                return False
                
        except docker.errors.NotFound:
            return False
        except Exception as e:
            self.logger.error(f"Health check error for {bot_name}: {e}")
            return False

    async def _handle_bot_crash(self, bot_name: str, config: Dict):
        """Handle bot crash with retry logic"""
        max_retries = config.get('max_retries', 3)
        retry_delay = config.get('retry_delay', 60)
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Attempting to restart {bot_name} (attempt {attempt + 1}/{max_retries})")
                
                from .runner import BotRunner
                runner = BotRunner()
                
                success = await runner.restart_bot(bot_name)
                
                if success:
                    self.logger.info(f"Successfully restarted {bot_name}")
                    
                    if config.get('webhook_url'):
                        await self.webhook.send_notification(
                            config['webhook_url'],
                            f"🔄 Bot **{bot_name}** automatically restarted after crash (attempt {attempt + 1})",
                            "warning"
                        )
                    return
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    
            except Exception as e:
                self.logger.error(f"Restart attempt {attempt + 1} failed for {bot_name}: {e}")
        
        # All retries failed
        self.logger.error(f"Failed to restart {bot_name} after {max_retries} attempts")
        
        if config.get('webhook_url'):
            await self.webhook.send_notification(
                config['webhook_url'],
                f"🚨 Bot **{bot_name}** crashed and failed to restart after {max_retries} attempts",
                "error"
            )

    async def _handle_container_crash(self, bot_name: str, container):
        """Handle when we detect a crashed container"""
        try:
            Bot = Query()
            bot_record = self.bots_table.get(Bot.name == bot_name)
            
            if not bot_record or bot_record.get('status') != 'running':
                return
            
            # Update status to crashed
            self.bots_table.update({
                'status': 'crashed',
                'crashed_at': time.time(),
                'exit_code': container.attrs.get('State', {}).get('ExitCode', -1)
            }, Bot.name == bot_name)
            
            config = bot_record.get('config', {})
            
            if config.get('restart_on_crash', True):
                await self._handle_bot_crash(bot_name, config)
            
        except Exception as e:
            self.logger.error(f"Error handling container crash for {bot_name}: {e}")

    def _setup_git_watchers(self):
        """Setup file watchers for git repositories"""
        try:
            bots_dir = Path('bots')
            if not bots_dir.exists():
                return
                
            self.observer = Observer()
            
            for bot_dir in bots_dir.iterdir():
                if bot_dir.is_dir() and (bot_dir / '.git').exists():
                    config_file = bot_dir / 'config.json'
                    if config_file.exists():
                        with open(config_file, 'r') as f:
                            config = json.load(f)
                        
                        if config.get('git_auto_pull', False):
                            self.observer.schedule(
                                GitWatcher(self),
                                str(bot_dir / '.git'),
                                recursive=True
                            )
                            self.logger.info(f"Watching git repo for {bot_dir.name}")
            
            self.observer.start()
            
        except Exception as e:
            self.logger.error(f"Failed to setup git watchers: {e}")

    async def handle_git_update(self, bot_name: str):
        """Handle git repository updates"""
        try:
            self.logger.info(f"Git update detected for {bot_name}")
            
            bot_dir = Path(f'bots/{bot_name}')
            
            # Pull latest changes
            result = await asyncio.create_subprocess_exec(
                'git', 'pull', 'origin', 'main',
                cwd=bot_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                self.logger.info(f"Git pull successful for {bot_name}")
                
                # Restart the bot
                from .runner import BotRunner
                runner = BotRunner()
                await runner.restart_bot(bot_name)
                
                # Send webhook notification
                Bot = Query()
                bot_record = self.bots_table.get(Bot.name == bot_name)
                if bot_record and bot_record.get('config', {}).get('webhook_url'):
                    await self.webhook.send_notification(
                        bot_record['config']['webhook_url'],
                        f"🔄 Bot **{bot_name}** updated from git and restarted",
                        "info"
                    )
            else:
                self.logger.error(f"Git pull failed for {bot_name}: {stderr.decode()}")
                
        except Exception as e:
            self.logger.error(f"Git update error for {bot_name}: {e}")

    async def tail_logs(self, bot_name: str):
        """Tail logs for a specific bot"""
        try:
            log_file = Path(f"bots/{bot_name}/logs/bot.log")
            
            if not log_file.exists():
                self.logger.error(f"Log file not found: {log_file}")
                return
            
            # Follow the log file
            with open(log_file, 'r') as f:
                f.seek(0, 2)  # Go to end of file
                
                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.1)
                        continue
                    print(line.strip())
                    
        except KeyboardInterrupt:
            pass
        except Exception as e:
            self.logger.error(f"Error tailing logs for {bot_name}: {e}")

    async def get_bot_metrics(self, bot_name: str) -> Dict:
        """Get detailed metrics for a bot"""
        try:
            container_name = f"t10_{bot_name}"
            container = self.docker_client.containers.get(container_name)
            
            stats = container.stats(stream=False)
            
            # Calculate CPU usage
            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                       stats['precpu_stats']['cpu_usage']['total_usage']
            system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                          stats['precpu_stats']['system_cpu_usage']
            cpu_percent = (cpu_delta / system_delta) * 100.0
            
            # Calculate memory usage
            memory_usage = stats['memory_stats']['usage']
            memory_limit = stats['memory_stats']['limit']
            memory_percent = (memory_usage / memory_limit) * 100.0
            
            return {
                'cpu_percent': round(cpu_percent, 2),
                'memory_usage_mb': round(memory_usage / 1024 / 1024, 2),
                'memory_percent': round(memory_percent, 2),
                'status': container.status,
                'uptime': self._get_container_uptime(container),
                'nitrix_monitored': True
            }
            
        except docker.errors.NotFound:
            return {'error': 'Container not found'}
        except Exception as e:
            self.logger.error(f"Error getting metrics for {bot_name}: {e}")
            return {'error': str(e)}

    def _get_container_uptime(self, container) -> str:
        """Calculate container uptime"""
        try:
            started_at = container.attrs['State']['StartedAt']
            from datetime import datetime
            start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            uptime = datetime.now(start_time.tzinfo) - start_time
            
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            if days > 0:
                return f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{minutes}m"
                
        except Exception:
            return "Unknown"

    def stop_monitoring(self):
        """Stop the monitoring system"""
        self.running = False
        if hasattr(self, 'observer'):
            self.observer.stop()
            self.observer.join()
        self.logger.info("Monitoring stopped")
