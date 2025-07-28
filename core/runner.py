import asyncio
import json
import subprocess
import time
import signal
import os
from pathlib import Path
from typing import Dict, List, Optional
import docker
import psutil
from tinydb import TinyDB, Query

from utils.logger import get_logger
from utils.validator import TokenValidator
from utils.webhook import WebhookNotifier

class BotRunner:
    def __init__(self):
        self.db = TinyDB('data/t10.db')
        self.bots_table = self.db.table('bots')
        self.logger = get_logger('runner')
        self.docker_client = docker.from_env()
        self.validator = TokenValidator()
        self.webhook = WebhookNotifier()
        self.nitrix_processes = {}
        
        os.makedirs('data', exist_ok=True)
        os.makedirs('bots', exist_ok=True)

    async def start_bot(self, bot_name: str, config_path: Optional[str] = None, env_path: Optional[str] = None) -> bool:
        try:
            bot_dir = Path(f"bots/{bot_name}")
            if not bot_dir.exists():
                self.logger.error(f"Bot directory not found: {bot_dir}")
                return False

            config_file = bot_dir / (config_path or "config.json")
            if not config_file.exists():
                self.logger.error(f"Config file not found: {config_file}")
                return False

            with open(config_file, 'r') as f:
                config = json.load(f)

            env_file = bot_dir / (env_path or config.get('env_file', 'env'))
            if not env_file.exists():
                self.logger.error(f"Environment file not found: {env_file}")
                return False

            if await self._is_bot_running(bot_name):
                self.logger.warning(f"Bot {bot_name} is already running")
                return False

            token = self._extract_token_from_env(env_file)
            if token and not await self.validator.validate_token(token):
                self.logger.error(f"Invalid token for bot {bot_name}")
                return False

            success = await self._start_docker_container(bot_name, config, bot_dir)
            
            if success:
                self._update_bot_record(bot_name, 'running', config)
                self.logger.info(f"Bot {bot_name} started successfully")
                
                if config.get('webhook_url'):
                    await self.webhook.send_notification(
                        config['webhook_url'],
                        f"🚀 Bot **{bot_name}** started successfully",
                        "success"
                    )
            
            return success

        except Exception as e:
            self.logger.error(f"Failed to start bot {bot_name}: {e}")
            return False

    async def stop_bot(self, bot_name: str) -> bool:
        try:
            container_name = f"t10_{bot_name}"
            
            try:
                container = self.docker_client.containers.get(container_name)
                container.stop(timeout=10)
                container.remove()
                self.logger.info(f"Stopped Docker container for {bot_name}")
            except docker.errors.NotFound:
                self.logger.warning(f"Container {container_name} not found")
            
            Bot = Query()
            self.bots_table.update({'status': 'stopped', 'stopped_at': time.time()}, 
                                 Bot.name == bot_name)
            
            if bot_name in self.nitrix_processes:
                del self.nitrix_processes[bot_name]
            
            return True

        except Exception as e:
            self.logger.error(f"Failed to stop bot {bot_name}: {e}")
            return False

    async def restart_bot(self, bot_name: str) -> bool:
        try:
            await self.stop_bot(bot_name)
            await asyncio.sleep(2)
            return await self.start_bot(bot_name)
        except Exception as e:
            self.logger.error(f"Failed to restart bot {bot_name}: {e}")
            return False

    async def list_bots(self) -> List[Dict]:
        try:
            bots = []
            for record in self.bots_table.all():
                bot_info = {
                    'name': record['name'],
                    'status': record.get('status', 'unknown'),
                    'started_at': record.get('started_at'),
                    'uptime': self._calculate_uptime(record.get('started_at'))
                }
                bots.append(bot_info)
            return bots
        except Exception as e:
            self.logger.error(f"Failed to list bots: {e}")
            return []

    async def _start_docker_container(self, bot_name: str, config: Dict, bot_dir: Path) -> bool:
        try:
            container_name = f"t10_{bot_name}"
            dockerfile_path = bot_dir / config.get('dockerfile', 'dockerfile')
            
            if not dockerfile_path.exists():
                self.logger.error(f"Dockerfile not found: {dockerfile_path}")
                return False

            try:
                existing_container = self.docker_client.containers.get(container_name)
                existing_container.remove(force=True)
            except docker.errors.NotFound:
                pass

            image_tag = f"t10/{bot_name}:latest"
            self.docker_client.images.build(
                path=str(bot_dir),
                dockerfile=config.get('dockerfile', 'dockerfile'),
                tag=image_tag,
                rm=True
            )

            env_vars = self._load_env_file(bot_dir / config.get('env_file', 'env'))
            
            container = self.docker_client.containers.run(
                image_tag,
                name=container_name,
                detach=True,
                environment=env_vars,
                restart_policy={"Name": "unless-stopped"} if config.get('auto_restart') else None,
                volumes={
                    str(bot_dir / 'logs'): {'bind': '/app/logs', 'mode': 'rw'}
                }
            )

            self.nitrix_processes[bot_name] = {
                'container_id': container.id,
                'started_at': time.time()
            }

            return True

        except Exception as e:
            self.logger.error(f"Failed to start Docker container for {bot_name}: {e}")
            return False

    async def _is_bot_running(self, bot_name: str) -> bool:
        try:
            container_name = f"t10_{bot_name}"
            container = self.docker_client.containers.get(container_name)
            return container.status == 'running'
        except docker.errors.NotFound:
            return False
        except Exception as e:
            self.logger.error(f"Error checking bot status: {e}")
            return False

    def _extract_token_from_env(self, env_file: Path) -> Optional[str]:
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    if line.strip().startswith('BOT_TOKEN='):
                        return line.strip().split('=', 1)[1].strip('"\'')
            return None
        except Exception as e:
            self.logger.error(f"Failed to extract token from {env_file}: {e}")
            return None

    def _load_env_file(self, env_file: Path) -> Dict[str, str]:
        env_vars = {}
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip().strip('"\'')
        except Exception as e:
            self.logger.error(f"Failed to load env file {env_file}: {e}")
        return env_vars

    def _update_bot_record(self, bot_name: str, status: str, config: Dict):
        Bot = Query()
        record = {
            'name': bot_name,
            'status': status,
            'config': config,
            'started_at': time.time() if status == 'running' else None,
            'nitrix_managed': True
        }
        
        if self.bots_table.search(Bot.name == bot_name):
            self.bots_table.update(record, Bot.name == bot_name)
        else:
            self.bots_table.insert(record)

    def _calculate_uptime(self, started_at: Optional[float]) -> str:
        if not started_at:
            return "N/A"
        
        uptime_seconds = time.time() - started_at
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    async def health_check(self) -> Dict[str, any]:
        """Health check for monitoring"""
        try:
            total_bots = len(self.bots_table.all())
            running_bots = len([b for b in self.bots_table.all() if b.get('status') == 'running'])
            
            return {
                'status': 'healthy',
                'total_bots': total_bots,
                'running_bots': running_bots,
                'timestamp': time.time(),
                'nitrix_version': '1.0.0'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': time.time()
      }
