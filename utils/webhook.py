import aiohttp
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict
from pathlib import Path

from utils.logger import get_logger

class WebhookNotifier:
    def __init__(self):
        self.logger = get_logger('webhook')
        self.rate_limits = {}
        self.nitrix_signature = "t10-bot-manager"
        
    async def send_notification(self, webhook_url: str, message: str, 
                               notification_type: str = "info", 
                               embed: Optional[Dict] = None) -> bool:
        """Send notification to Discord webhook"""
        try:
            if not webhook_url:
                return False
            
            # Rate limiting check
            if await self._is_rate_limited(webhook_url):
                self.logger.warning(f"Webhook rate limited: {webhook_url}")
                return False
            
            payload = await self._create_payload(message, notification_type, embed)
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 204:
                        self.logger.info("Webhook notification sent successfully")
                        await self._update_rate_limit(webhook_url)
                        return True
                    elif response.status == 429:
                        self.logger.warning("Webhook rate limited by Discord")
                        await self._handle_rate_limit(webhook_url, response)
                        return False
                    else:
                        self.logger.error(f"Webhook failed with status {response.status}")
                        return False
                        
        except asyncio.TimeoutError:
            self.logger.error("Webhook request timed out")
            return False
        except Exception as e:
            self.logger.error(f"Webhook error: {e}")
            return False

    async def send_bot_status(self, webhook_url: str, bot_name: str, 
                             status: str, details: Optional[Dict] = None) -> bool:
        """Send bot status update via webhook"""
        try:
            color_map = {
                'started': 0x00ff00,  # Green
                'stopped': 0xffff00,  # Yellow
                'crashed': 0xff0000,  # Red
                'restarted': 0x0099ff  # Blue
            }
            
            embed = {
                'title': f'Bot Status Update',
                'color': color_map.get(status, 0x808080),
                'fields': [
                    {
                        'name': 'Bot Name',
                        'value': bot_name,
                        'inline': True
                    },
                    {
                        'name': 'Status',
                        'value': status.title(),
                        'inline': True
                    },
                    {
                        'name': 'Timestamp',
                        'value': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'inline': True
                    }
                ],
                'footer': {
                    'text': f'Managed by {self.nitrix_signature}'
                }
            }
            
            if details:
                for key, value in details.items():
                    embed['fields'].append({
                        'name': key.replace('_', ' ').title(),
                        'value': str(value),
                        'inline': True
                    })
            
            status_emojis = {
                'started': '🚀',
                'stopped': '⏹️',
                'crashed': '💥',
                'restarted': '🔄'
            }
            
            message = f"{status_emojis.get(status, '📊')} Bot **{bot_name}** {status}"
            
            return await self.send_notification(webhook_url, message, status, embed)
            
        except Exception as e:
            self.logger.error(f"Failed to send bot status: {e}")
            return False

    async def send_system_alert(self, webhook_url: str, alert_type: str, 
                               message: str, severity: str = "warning") -> bool:
        """Send system alert via webhook"""
        try:
            severity_colors = {
                'info': 0x0099ff,
                'warning': 0xffaa00,
                'error': 0xff0000,
                'critical': 0x990000
            }
            
            severity_emojis = {
                'info': 'ℹ️',
                'warning': '⚠️',
                'error': '❌',
                'critical': '🚨'
            }
            
            embed = {
                'title': f'{severity_emojis.get(severity, "🔔")} System Alert',
                'description': message,
                'color': severity_colors.get(severity, 0x808080),
                'fields': [
                    {
                        'name': 'Alert Type',
                        'value': alert_type,
                        'inline': True
                    },
                    {
                        'name': 'Severity',
                        'value': severity.upper(),
                        'inline': True
                    },
                    {
                        'name': 'Time',
                        'value': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'inline': True
                    }
                ],
                'footer': {
                    'text': f'Nitrix t10 System Monitor'
                }
            }
            
            alert_message = f"{severity_emojis.get(severity, '🔔')} **{alert_type}**: {message}"
            
            return await self.send_notification(webhook_url, alert_message, severity, embed)
            
        except Exception as e:
            self.logger.error(f"Failed to send system alert: {e}")
            return False

    async def send_crash_report(self, webhook_url: str, bot_name: str, 
                               error: str, attempt_count: int = 1) -> bool:
        """Send detailed crash report via webhook"""
        try:
            embed = {
                'title': '💥 Bot Crash Report',
                'color': 0xff0000,
                'fields': [
                    {
                        'name': 'Bot Name',
                        'value': bot_name,
                        'inline': True
                    },
                    {
                        'name': 'Restart Attempt',
                        'value': f"#{attempt_count}",
                        'inline': True
                    },
                    {
                        'name': 'Crash Time',
                        'value': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'inline': True
                    },
                    {
                        'name': 'Error Details',
                        'value': f"```{error[:1000]}```",  # Limit error length
                        'inline': False
                    }
                ],
                'footer': {
                    'text': f'Auto-restart enabled | {self.nitrix_signature}'
                }
            }
            
            message = f"🚨 Bot **{bot_name}** has crashed and is being restarted (attempt #{attempt_count})"
            
            return await self.send_notification(webhook_url, message, "error", embed)
            
        except Exception as e:
            self.logger.error(f"Failed to send crash report: {e}")
            return False

    async def send_health_report(self, webhook_url: str, health_data: Dict) -> bool:
        """Send system health report via webhook"""
        try:
            total_bots = health_data.get('total_bots', 0)
            running_bots = health_data.get('running_bots', 0)
            
            health_status = "🟢 Healthy" if running_bots == total_bots else "🟡 Partial"
            if running_bots == 0 and total_bots > 0:
                health_status = "🔴 Critical"
            
            embed = {
                'title': '📊 System Health Report',
                'color': 0x00ff00 if running_bots == total_bots else 0xffaa00,
                'fields': [
                    {
                        'name': 'System Status',
                        'value': health_status,
                        'inline': True
                    },
                    {
                        'name': 'Total Bots',
                        'value': str(total_bots),
                        'inline': True
                    },
                    {
                        'name': 'Running Bots',
                        'value': str(running_bots),
                        'inline': True
                    },
                    {
                        'name': 'Uptime',
                        'value': health_data.get('uptime', 'Unknown'),
                        'inline': True
                    },
                    {
                        'name': 'Memory Usage',
                        'value': f"{health_data.get('memory_percent', 0):.1f}%",
                        'inline': True
                    },
                    {
                        'name': 'CPU Usage',
                        'value': f"{health_data.get('cpu_percent', 0):.1f}%",
                        'inline': True
                    }
                ],
                'timestamp': datetime.now().isoformat(),
                'footer': {
                    'text': f'{self.nitrix_signature} v1.0.0'
                }
            }
            
            message = f"📊 System health check complete - {health_status}"
            
            return await self.send_notification(webhook_url, message, "info", embed)
            
        except Exception as e:
            self.logger.error(f"Failed to send health report: {e}")
            return False

    async def _create_payload(self, message: str, notification_type: str, 
                             embed: Optional[Dict] = None) -> Dict:
        """Create webhook payload"""
        payload = {
            'content': message,
            'username': 't10 Bot Manager',
            'avatar_url': None  # Could add a custom avatar URL here
        }
        
        if embed:
            payload['embeds'] = [embed]
        
        return payload

    async def _is_rate_limited(self, webhook_url: str) -> bool:
        """Check if webhook is rate limited"""
        try:
            if webhook_url not in self.rate_limits:
                return False
            
            last_request = self.rate_limits[webhook_url]['last_request']
            min_interval = self.rate_limits[webhook_url].get('min_interval', 5)
            
            return (datetime.now().timestamp() - last_request) < min_interval
            
        except Exception:
            return False

    async def _update_rate_limit(self, webhook_url: str):
        """Update rate limit information"""
        try:
            if webhook_url not in self.rate_limits:
                self.rate_limits[webhook_url] = {}
            
            self.rate_limits[webhook_url]['last_request'] = datetime.now().timestamp()
            
        except Exception as e:
            self.logger.error(f"Failed to update rate limit: {e}")

    async def _handle_rate_limit(self, webhook_url: str, response):
        """Handle Discord rate limit response"""
        try:
            if 'retry-after' in response.headers:
                retry_after = int(response.headers['retry-after'])
                if webhook_url not in self.rate_limits:
                    self.rate_limits[webhook_url] = {}
                
                self.rate_limits[webhook_url]['min_interval'] = retry_after
                self.logger.warning(f"Rate limited for {retry_after} seconds")
                
        except Exception as e:
            self.logger.error(f"Failed to handle rate limit: {e}")

    async def test_webhook(self, webhook_url: str) -> Dict:
        """Test webhook connectivity"""
        try:
            test_embed = {
                'title': '🧪 Webhook Test',
                'description': 'This is a test message from t10 Bot Manager',
                'color': 0x0099ff,
                'fields': [
                    {
                        'name': 'Status',
                        'value': 'Testing webhook connectivity',
                        'inline': True
                    },
                    {
                        'name': 'Timestamp',
                        'value': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
                        'inline': True
                    }
                ],
                'footer': {
                    'text': f'Powered by {self.nitrix_signature}'
                }
            }
            
            success = await self.send_notification(
                webhook_url, 
                "🧪 Testing webhook connection...", 
                "info", 
                test_embed
            )
            
            return {
                'success': success,
                'webhook_url': webhook_url,
                'tested_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'webhook_url': webhook_url,
                'tested_at': datetime.now().isoformat()
            }

    def get_webhook_stats(self) -> Dict:
        """Get webhook usage statistics"""
        try:
            return {
                'total_webhooks': len(self.rate_limits),
                'rate_limits': self.rate_limits,
                'nitrix_managed': True
            }
        except Exception as e:
            return {'error': str(e)}
