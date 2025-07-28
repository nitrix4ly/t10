import asyncio
import aiohttp
import re
from typing import Optional, Dict, Tuple
from pathlib import Path

from utils.logger import get_logger

class TokenValidator:
    def __init__(self):
        self.logger = get_logger('validator')
        self.discord_api_base = "https://discord.com/api/v10"
        
    async def validate_token(self, token: str) -> bool:
        """Validate Discord bot token"""
        try:
            if not self._is_valid_token_format(token):
                self.logger.error("Invalid token format")
                return False
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bot {token}',
                    'Content-Type': 'application/json'
                }
                
                async with session.get(
                    f"{self.discord_api_base}/users/@me",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        bot_info = await response.json()
                        self.logger.info(f"Token validated for bot: {bot_info.get('username', 'Unknown')}")
                        return True
                    elif response.status == 401:
                        self.logger.error("Invalid or expired token")
                        return False
                    else:
                        self.logger.error(f"Token validation failed with status {response.status}")
                        return False
                        
        except asyncio.TimeoutError:
            self.logger.error("Token validation timed out")
            return False
        except Exception as e:
            self.logger.error(f"Token validation error: {e}")
            return False

    async def get_bot_info(self, token: str) -> Optional[Dict]:
        """Get bot information using token"""
        try:
            if not await self.validate_token(token):
                return None
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bot {token}',
                    'Content-Type': 'application/json'
                }
                
                async with session.get(
                    f"{self.discord_api_base}/users/@me",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        bot_info = await response.json()
                        return {
                            'id': bot_info.get('id'),
                            'username': bot_info.get('username'),
                            'discriminator': bot_info.get('discriminator'),
                            'bot': bot_info.get('bot', False),
                            'verified': bot_info.get('verified', False),
                            'nitrix_validated': True
                        }
                    return None
                    
        except Exception as e:
            self.logger.error(f"Failed to get bot info: {e}")
            return None

    async def validate_bot_permissions(self, token: str, guild_id: Optional[str] = None) -> Dict:
        """Validate bot permissions in a guild"""
        try:
            permissions_info = {
                'valid_token': False,
                'in_guild': False,
                'permissions': [],
                'missing_common_permissions': []
            }
            
            if not await self.validate_token(token):
                return permissions_info
            
            permissions_info['valid_token'] = True
            
            if not guild_id:
                return permissions_info
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bot {token}',
                    'Content-Type': 'application/json'
                }
                
                # Check if bot is in guild
                async with session.get(
                    f"{self.discord_api_base}/guilds/{guild_id}/members/@me",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        permissions_info['in_guild'] = True
                        member_info = await response.json()
                        
                        # Get guild to check permissions
                        async with session.get(
                            f"{self.discord_api_base}/guilds/{guild_id}",
                            headers=headers
                        ) as guild_response:
                            if guild_response.status == 200:
                                guild_info = await guild_response.json()
                                permissions_info['guild_name'] = guild_info.get('name')
                                
                        permissions_info['roles'] = member_info.get('roles', [])
            
            return permissions_info
            
        except Exception as e:
            self.logger.error(f"Permission validation error: {e}")
            return {'error': str(e)}

    def _is_valid_token_format(self, token: str) -> bool:
        """Check if token has valid Discord bot token format"""
        if not token or not isinstance(token, str):
            return False
        
        # Remove Bot prefix if present
        token = token.replace('Bot ', '').strip()
        
        # Discord bot tokens are typically base64 encoded and have specific patterns
        # Basic format check: should be alphanumeric with dots and underscores
        pattern = r'^[A-Za-z0-9._-]+$'
        
        if not re.match(pattern, token):
            return False
        
        # Length check (Discord tokens are usually 59+ characters)
        if len(token) < 50:
            return False
        
        return True

    async def validate_config_file(self, config_path: Path) -> Tuple[bool, Dict]:
        """Validate bot configuration file"""
        try:
            if not config_path.exists():
                return False, {'error': 'Config file not found'}
            
            import json
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            validation_result = {
                'valid': True,
                'errors': [],
                'warnings': []
            }
            
            # Required fields
            required_fields = ['name', 'dockerfile', 'env_file']
            for field in required_fields:
                if field not in config:
                    validation_result['errors'].append(f"Missing required field: {field}")
                    validation_result['valid'] = False
            
            # Optional field validation
            if 'auto_restart' in config and not isinstance(config['auto_restart'], bool):
                validation_result['warnings'].append("auto_restart should be boolean")
            
            if 'restart_on_crash' in config and not isinstance(config['restart_on_crash'], bool):
                validation_result['warnings'].append("restart_on_crash should be boolean")
            
            if 'webhook_url' in config:
                webhook_url = config['webhook_url']
                if webhook_url and not self._is_valid_webhook_url(webhook_url):
                    validation_result['warnings'].append("Invalid webhook URL format")
            
            return validation_result['valid'], validation_result
            
        except json.JSONDecodeError:
            return False, {'error': 'Invalid JSON in config file'}
        except Exception as e:
            return False, {'error': f'Config validation error: {e}'}

    async def validate_env_file(self, env_path: Path) -> Tuple[bool, Dict]:
        """Validate bot environment file"""
        try:
            if not env_path.exists():
                return False, {'error': 'Environment file not found'}
            
            validation_result = {
                'valid': True,
                'errors': [],
                'warnings': [],
                'found_token': False
            }
            
            with open(env_path, 'r') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                if not line or line.startswith('#'):
                    continue
                
                if '=' not in line:
                    validation_result['warnings'].append(f"Line {line_num}: Invalid format, missing '='")
                    continue
                
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                
                if key == 'BOT_TOKEN':
                    validation_result['found_token'] = True
                    if not value or value == 'your_bot_token_here':
                        validation_result['errors'].append("BOT_TOKEN is empty or placeholder")
                        validation_result['valid'] = False
                    elif not self._is_valid_token_format(value):
                        validation_result['errors'].append("BOT_TOKEN has invalid format")
                        validation_result['valid'] = False
            
            if not validation_result['found_token']:
                validation_result['errors'].append("BOT_TOKEN not found in environment file")
                validation_result['valid'] = False
            
            return validation_result['valid'], validation_result
            
        except Exception as e:
            return False, {'error': f'Environment file validation error: {e}'}

    async def validate_dockerfile(self, dockerfile_path: Path) -> Tuple[bool, Dict]:
        """Validate Dockerfile"""
        try:
            if not dockerfile_path.exists():
                return False, {'error': 'Dockerfile not found'}
            
            validation_result = {
                'valid': True,
                'errors': [],
                'warnings': [],
                'has_from': False,
                'has_workdir': False,
                'has_copy': False,
                'has_cmd': False
            }
            
            with open(dockerfile_path, 'r') as f:
                content = f.read().upper()
            
            # Check for essential Dockerfile instructions
            if 'FROM' in content:
                validation_result['has_from'] = True
            else:
                validation_result['errors'].append("Missing FROM instruction")
                validation_result['valid'] = False
            
            if 'WORKDIR' in content:
                validation_result['has_workdir'] = True
            else:
                validation_result['warnings'].append("Missing WORKDIR instruction (recommended)")
            
            if 'COPY' in content or 'ADD' in content:
                validation_result['has_copy'] = True
            else:
                validation_result['warnings'].append("No COPY/ADD instructions found")
            
            if 'CMD' in content or 'ENTRYPOINT' in content:
                validation_result['has_cmd'] = True
            else:
                validation_result['errors'].append("Missing CMD or ENTRYPOINT instruction")
                validation_result['valid'] = False
            
            return validation_result['valid'], validation_result
            
        except Exception as e:
            return False, {'error': f'Dockerfile validation error: {e}'}

    def _is_valid_webhook_url(self, url: str) -> bool:
        """Validate Discord webhook URL format"""
        if not url:
            return False
        
        # Discord webhook URL pattern
        webhook_pattern = r'https://discord(?:app)?\.com/api/webhooks/\d+/[\w-]+'
        return re.match(webhook_pattern, url) is not None

    async def validate_bot_setup(self, bot_name: str) -> Dict:
        """Comprehensive bot setup validation"""
        try:
            bot_dir = Path(f'bots/{bot_name}')
            
            validation_result = {
                'bot_name': bot_name,
                'overall_valid': True,
                'config_valid': False,
                'env_valid': False,
                'dockerfile_valid': False,
                'token_valid': False,
                'errors': [],
                'warnings': [],
                'nitrix_validated': True
            }
            
            if not bot_dir.exists():
                validation_result['errors'].append(f"Bot directory not found: {bot_dir}")
                validation_result['overall_valid'] = False
                return validation_result
            
            # Validate config file
            config_path = bot_dir / 'config.json'
            config_valid, config_result = await self.validate_config_file(config_path)
            validation_result['config_valid'] = config_valid
            
            if not config_valid:
                validation_result['errors'].extend(config_result.get('errors', []))
                validation_result['overall_valid'] = False
            
            validation_result['warnings'].extend(config_result.get('warnings', []))
            
            # Load config for further validation
            config = {}
            if config_valid:
                with open(config_path, 'r') as f:
                    config = json.load(f)
            
            # Validate environment file
            env_file = config.get('env_file', 'env')
            env_path = bot_dir / env_file
            env_valid, env_result = await self.validate_env_file(env_path)
            validation_result['env_valid'] = env_valid
            
            if not env_valid:
                validation_result['errors'].extend(env_result.get('errors', []))
                validation_result['overall_valid'] = False
            
            validation_result['warnings'].extend(env_result.get('warnings', []))
            
            # Validate Dockerfile
            dockerfile = config.get('dockerfile', 'dockerfile')
            dockerfile_path = bot_dir / dockerfile
            dockerfile_valid, dockerfile_result = await self.validate_dockerfile(dockerfile_path)
            validation_result['dockerfile_valid'] = dockerfile_valid
            
            if not dockerfile_valid:
                validation_result['errors'].extend(dockerfile_result.get('errors', []))
                validation_result['overall_valid'] = False
            
            validation_result['warnings'].extend(dockerfile_result.get('warnings', []))
            
            # Validate token if environment is valid
            if env_valid and env_result.get('found_token'):
                token = self._extract_token_from_env_file(env_path)
                if token:
                    token_valid = await self.validate_token(token)
                    validation_result['token_valid'] = token_valid
                    
                    if not token_valid:
                        validation_result['errors'].append("Bot token validation failed")
                        validation_result['overall_valid'] = False
            
            self.logger.info(f"Bot setup validation for {bot_name}: {'PASSED' if validation_result['overall_valid'] else 'FAILED'}")
            
            return validation_result
            
        except Exception as e:
            self.logger.error(f"Bot setup validation error: {e}")
            return {
                'bot_name': bot_name,
                'overall_valid': False,
                'error': str(e)
            }

    def _extract_token_from_env_file(self, env_path: Path) -> Optional[str]:
        """Extract bot token from environment file"""
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('BOT_TOKEN='):
                        return line.split('=', 1)[1].strip().strip('"\'')
            return None
        except Exception as e:
            self.logger.error(f"Failed to extract token from {env_path}: {e}")
            return None

    async def batch_validate_bots(self) -> Dict:
        """Validate all bots in the bots directory"""
        try:
            bots_dir = Path('bots')
            if not bots_dir.exists():
                return {'error': 'Bots directory not found'}
            
            results = {
                'total_bots': 0,
                'valid_bots': 0,
                'invalid_bots': 0,
                'bot_results': {},
                'summary': {
                    'config_issues': 0,
                    'env_issues': 0,
                    'dockerfile_issues': 0,
                    'token_issues': 0
                }
            }
            
            for bot_dir in bots_dir.iterdir():
                if bot_dir.is_dir():
                    bot_name = bot_dir.name
                    results['total_bots'] += 1
                    
                    validation = await self.validate_bot_setup(bot_name)
                    results['bot_results'][bot_name] = validation
                    
                    if validation['overall_valid']:
                        results['valid_bots'] += 1
                    else:
                        results['invalid_bots'] += 1
                        
                        # Count specific issue types
                        if not validation.get('config_valid', True):
                            results['summary']['config_issues'] += 1
                        if not validation.get('env_valid', True):
                            results['summary']['env_issues'] += 1
                        if not validation.get('dockerfile_valid', True):
                            results['summary']['dockerfile_issues'] += 1
                        if not validation.get('token_valid', True):
                            results['summary']['token_issues'] += 1
            
            return results
            
        except Exception as e:
            self.logger.error(f"Batch validation error: {e}")
            return {'error': str(e)}
