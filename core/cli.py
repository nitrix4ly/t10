import click
import asyncio
import json
import os
from pathlib import Path
from colorama import init, Fore, Style

from .runner import BotRunner
from .monitor import BotMonitor
from .scheduler import BotScheduler
from utils.validator import TokenValidator
from utils.logger import setup_logging

init(autoreset=True)

class NitrixContext:
    def __init__(self):
        self.runner = BotRunner()
        self.monitor = BotMonitor()
        self.scheduler = BotScheduler()
        self.validator = TokenValidator()

@click.group()
@click.pass_context
def cli(ctx):
    """t10 - Discord Bot Process Manager"""
    ctx.ensure_object(dict)
    ctx.obj = NitrixContext()
    setup_logging()

@cli.command()
@click.argument('bot_name')
@click.option('--config', '-c', help='Custom config file path')
@click.option('--env', '-e', help='Custom env file path')
@click.pass_obj
def start(obj, bot_name, config, env):
    """Start a Discord bot"""
    try:
        result = asyncio.run(obj.runner.start_bot(bot_name, config, env))
        if result:
            click.echo(f"{Fore.GREEN}✅ Bot '{bot_name}' started successfully")
        else:
            click.echo(f"{Fore.RED}❌ Failed to start bot '{bot_name}'")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.pass_obj
def stop(obj, bot_name):
    """Stop a Discord bot"""
    try:
        result = asyncio.run(obj.runner.stop_bot(bot_name))
        if result:
            click.echo(f"{Fore.YELLOW}⏹️  Bot '{bot_name}' stopped")
        else:
            click.echo(f"{Fore.RED}❌ Bot '{bot_name}' not found or already stopped")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.pass_obj
def restart(obj, bot_name):
    """Restart a Discord bot"""
    try:
        result = asyncio.run(obj.runner.restart_bot(bot_name))
        if result:
            click.echo(f"{Fore.CYAN}🔄 Bot '{bot_name}' restarted")
        else:
            click.echo(f"{Fore.RED}❌ Failed to restart bot '{bot_name}'")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.pass_obj
def status(obj):
    """Show status of all bots"""
    try:
        bots = asyncio.run(obj.runner.list_bots())
        if not bots:
            click.echo(f"{Fore.YELLOW}📭 No bots are currently running")
            return
        
        click.echo(f"{Fore.CYAN}📊 Bot Status:")
        click.echo("-" * 60)
        for bot in bots:
            status_color = Fore.GREEN if bot['status'] == 'running' else Fore.RED
            uptime = bot.get('uptime', 'N/A')
            click.echo(f"{status_color}{bot['name']:<20} {bot['status']:<10} {uptime}")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.option('--lines', '-n', default=50, help='Number of lines to show')
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
@click.pass_obj
def logs(obj, bot_name, lines, follow):
    """Show bot logs"""
    try:
        log_file = Path(f"bots/{bot_name}/logs/bot.log")
        if not log_file.exists():
            click.echo(f"{Fore.RED}❌ No logs found for bot '{bot_name}'")
            return
        
        if follow:
            asyncio.run(obj.monitor.tail_logs(bot_name))
        else:
            with open(log_file, 'r') as f:
                log_lines = f.readlines()
                for line in log_lines[-lines:]:
                    click.echo(line.strip())
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.argument('schedule_time', help='Schedule format: "2h", "30m", "1d"')
@click.pass_obj
def schedule(obj, bot_name, schedule_time):
    """Schedule automatic restart for a bot"""
    try:
        result = obj.scheduler.add_schedule(bot_name, schedule_time)
        if result:
            click.echo(f"{Fore.GREEN}⏰ Scheduled restart for '{bot_name}' every {schedule_time}")
        else:
            click.echo(f"{Fore.RED}❌ Failed to schedule restart for '{bot_name}'")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.pass_obj
def unschedule(obj, bot_name):
    """Remove scheduled restart for a bot"""
    try:
        result = obj.scheduler.remove_schedule(bot_name)
        if result:
            click.echo(f"{Fore.YELLOW}⏰ Removed schedule for '{bot_name}'")
        else:
            click.echo(f"{Fore.RED}❌ No schedule found for '{bot_name}'")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.option('--token', prompt=True, hide_input=True, help='Bot token to validate')
@click.pass_obj
def validate(obj, bot_name, token):
    """Validate bot token"""
    try:
        result = asyncio.run(obj.validator.validate_token(token))
        if result:
            click.echo(f"{Fore.GREEN}✅ Token is valid for bot '{bot_name}'")
        else:
            click.echo(f"{Fore.RED}❌ Invalid token for bot '{bot_name}'")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.option('--dockerfile', default='dockerfile', help='Dockerfile name')
@click.option('--env-file', default='env', help='Environment file name')
@click.pass_obj
def add(obj, bot_name, dockerfile, env_file):
    """Add a new bot configuration"""
    try:
        bot_dir = Path(f"bots/{bot_name}")
        bot_dir.mkdir(parents=True, exist_ok=True)
        
        config = {
            "name": bot_name,
            "dockerfile": dockerfile,
            "env_file": env_file,
            "auto_restart": True,
            "restart_on_crash": True,
            "git_auto_pull": False,
            "webhook_url": None,
            "nitrix_managed": True
        }
        
        config_file = bot_dir / "config.json"
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        dockerfile_path = bot_dir / dockerfile
        if not dockerfile_path.exists():
            dockerfile_content = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
"""
            with open(dockerfile_path, 'w') as f:
                f.write(dockerfile_content)
        
        env_path = bot_dir / env_file
        if not env_path.exists():
            with open(env_path, 'w') as f:
                f.write("BOT_TOKEN=your_bot_token_here\n")
        
        click.echo(f"{Fore.GREEN}✅ Bot '{bot_name}' configuration created")
        click.echo(f"📁 Directory: {bot_dir}")
        click.echo(f"⚠️  Don't forget to update the env file with your bot token!")
        
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.argument('bot_name')
@click.pass_obj
def remove(obj, bot_name):
    """Remove a bot configuration"""
    try:
        result = asyncio.run(obj.runner.stop_bot(bot_name))
        
        bot_dir = Path(f"bots/{bot_name}")
        if bot_dir.exists():
            import shutil
            shutil.rmtree(bot_dir)
            click.echo(f"{Fore.YELLOW}🗑️  Bot '{bot_name}' removed")
        else:
            click.echo(f"{Fore.RED}❌ Bot '{bot_name}' not found")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.pass_obj
def monitor(obj):
    """Start monitoring mode (runs in background)"""
    try:
        click.echo(f"{Fore.CYAN}👁️  Starting t10 monitor...")
        asyncio.run(obj.monitor.start_monitoring())
    except KeyboardInterrupt:
        click.echo(f"{Fore.YELLOW}⏹️  Monitor stopped")
    except Exception as e:
        click.echo(f"{Fore.RED}❌ Error: {e}")

@cli.command()
@click.pass_obj
def version(obj):
    """Show t10 version"""
    click.echo(f"{Fore.CYAN}t10 v1.0.0 - Discord Bot Manager")
    click.echo(f"{Fore.GREEN}Built with ❤️  by Nitrix")
