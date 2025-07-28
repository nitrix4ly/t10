import asyncio
import schedule
import time
import threading
from typing import Dict, Optional
from tinydb import TinyDB, Query
import re

from utils.logger import get_logger

class BotScheduler:
    def __init__(self):
        self.db = TinyDB('data/t10.db')
        self.schedules_table = self.db.table('schedules')
        self.logger = get_logger('scheduler')
        self.scheduler_thread = None
        self.running = False
        self.nitrix_scheduler_active = False
        
    def add_schedule(self, bot_name: str, schedule_time: str) -> bool:
        """Add scheduled restart for a bot"""
        try:
            interval = self._parse_schedule_time(schedule_time)
            if not interval:
                self.logger.error(f"Invalid schedule format: {schedule_time}")
                return False
            
            Schedule = Query()
            existing = self.schedules_table.get(Schedule.bot_name == bot_name)
            
            schedule_record = {
                'bot_name': bot_name,
                'schedule_time': schedule_time,
                'interval_minutes': interval,
                'created_at': time.time(),
                'last_run': None,
                'nitrix_managed': True
            }
            
            if existing:
                self.schedules_table.update(schedule_record, Schedule.bot_name == bot_name)
            else:
                self.schedules_table.insert(schedule_record)
            
            self._setup_schedule(bot_name, interval)
            self.logger.info(f"Scheduled restart for {bot_name} every {schedule_time}")
            
            if not self.running:
                self.start_scheduler()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to add schedule for {bot_name}: {e}")
            return False

    def remove_schedule(self, bot_name: str) -> bool:
        """Remove scheduled restart for a bot"""
        try:
            Schedule = Query()
            result = self.schedules_table.remove(Schedule.bot_name == bot_name)
            
            if result:
                # Clear from schedule module
                schedule.clear(bot_name)
                self.logger.info(f"Removed schedule for {bot_name}")
                return True
            else:
                self.logger.warning(f"No schedule found for {bot_name}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to remove schedule for {bot_name}: {e}")
            return False

    def list_schedules(self) -> list:
        """List all scheduled restarts"""
        try:
            schedules = []
            for record in self.schedules_table.all():
                schedule_info = {
                    'bot_name': record['bot_name'],
                    'schedule_time': record['schedule_time'],
                    'last_run': record.get('last_run'),
                    'next_run': self._calculate_next_run(record)
                }
                schedules.append(schedule_info)
            return schedules
        except Exception as e:
            self.logger.error(f"Failed to list schedules: {e}")
            return []

    def start_scheduler(self):
        """Start the scheduler in a separate thread"""
        if self.running:
            return
            
        self.running = True
        self.nitrix_scheduler_active = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        self.logger.info("Nitrix scheduler started")

    def stop_scheduler(self):
        """Stop the scheduler"""
        self.running = False
        self.nitrix_scheduler_active = False
        schedule.clear()
        self.logger.info("Scheduler stopped")

    def _run_scheduler(self):
        """Main scheduler loop"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
                time.sleep(60)

    def _setup_schedule(self, bot_name: str, interval_minutes: int):
        """Setup schedule for a specific bot"""
        try:
            schedule.clear(bot_name)
            
            if interval_minutes >= 1440:  # Daily or more
                days = interval_minutes // 1440
                schedule.every(days).days.do(self._restart_bot, bot_name).tag(bot_name)
            elif interval_minutes >= 60:  # Hourly
                hours = interval_minutes // 60
                schedule.every(hours).hours.do(self._restart_bot, bot_name).tag(bot_name)
            else:  # Minutes
                schedule.every(interval_minutes).minutes.do(self._restart_bot, bot_name).tag(bot_name)
                
        except Exception as e:
            self.logger.error(f"Failed to setup schedule for {bot_name}: {e}")

    def _restart_bot(self, bot_name: str):
        """Restart a bot (called by scheduler)"""
        try:
            self.logger.info(f"Scheduled restart triggered for {bot_name}")
            
            # Update last run time
            Schedule = Query()
            self.schedules_table.update(
                {'last_run': time.time()}, 
                Schedule.bot_name == bot_name
            )
            
            # Restart the bot
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                from .runner import BotRunner
                runner = BotRunner()
                result = loop.run_until_complete(runner.restart_bot(bot_name))
                
                if result:
                    self.logger.info(f"Scheduled restart successful for {bot_name}")
                else:
                    self.logger.error(f"Scheduled restart failed for {bot_name}")
            finally:
                loop.close()
                
        except Exception as e:
            self.logger.error(f"Scheduled restart error for {bot_name}: {e}")

    def _parse_schedule_time(self, schedule_time: str) -> Optional[int]:
        """Parse schedule time string to minutes"""
        try:
            schedule_time = schedule_time.lower().strip()
            
            # Match patterns like "2h", "30m", "1d", "2.5h"
            pattern = r'^(\d+(?:\.\d+)?)(h|m|d)$'
            match = re.match(pattern, schedule_time)
            
            if not match:
                return None
            
            value = float(match.group(1))
            unit = match.group(2)
            
            if unit == 'm':
                return int(value)
            elif unit == 'h':
                return int(value * 60)
            elif unit == 'd':
                return int(value * 1440)
                
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to parse schedule time {schedule_time}: {e}")
            return None

    def _calculate_next_run(self, record: Dict) -> Optional[str]:
        """Calculate next run time for a schedule"""
        try:
            last_run = record.get('last_run')
            interval_minutes = record.get('interval_minutes')
            
            if not last_run or not interval_minutes:
                return "Soon"
            
            next_run_timestamp = last_run + (interval_minutes * 60)
            current_time = time.time()
            
            if next_run_timestamp <= current_time:
                return "Overdue"
            
            time_until = next_run_timestamp - current_time
            
            if time_until >= 86400:  # More than a day
                days = int(time_until // 86400)
                return f"In {days}d"
            elif time_until >= 3600:  # More than an hour
                hours = int(time_until // 3600)
                return f"In {hours}h"
            else:  # Minutes
                minutes = int(time_until // 60)
                return f"In {minutes}m"
                
        except Exception as e:
            self.logger.error(f"Failed to calculate next run: {e}")
            return "Unknown"

    def get_scheduler_status(self) -> Dict:
        """Get scheduler status and statistics"""
        try:
            total_schedules = len(self.schedules_table.all())
            active_schedules = len([s for s in self.schedules_table.all() 
                                  if s.get('last_run') is not None])
            
            return {
                'running': self.running,
                'total_schedules': total_schedules,
                'active_schedules': active_schedules,
                'nitrix_managed': self.nitrix_scheduler_active
            }
        except Exception as e:
            return {
                'running': False,
                'error': str(e)
            }

    def force_run_schedule(self, bot_name: str) -> bool:
        """Force run a scheduled restart immediately"""
        try:
            Schedule = Query()
            schedule_record = self.schedules_table.get(Schedule.bot_name == bot_name)
            
            if not schedule_record:
                self.logger.error(f"No schedule found for {bot_name}")
                return False
            
            self._restart_bot(bot_name)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to force run schedule for {bot_name}: {e}")
            return False
