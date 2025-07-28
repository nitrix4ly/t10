import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logging():
    """Setup logging configuration for t10"""
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        logs_dir / 't10.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(simple_formatter)
    console_handler.setLevel(logging.WARNING)
    
    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Silence some noisy loggers
    logging.getLogger('docker').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name"""
    return logging.getLogger(f't10.{name}')

def setup_bot_logging(bot_name: str):
    """Setup logging for a specific bot"""
    bot_logs_dir = Path(f'bots/{bot_name}/logs')
    bot_logs_dir.mkdir(parents=True, exist_ok=True)
    
    bot_logger = logging.getLogger(f'bot.{bot_name}')
    bot_logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    bot_logger.handlers.clear()
    
    # Bot-specific file handler
    bot_file_handler = RotatingFileHandler(
        bot_logs_dir / 'bot.log',
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3
    )
    
    bot_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    bot_file_handler.setFormatter(bot_formatter)
    bot_logger.addHandler(bot_file_handler)
    bot_logger.propagate = False
    
    return bot_logger

class NitrixLogFilter(logging.Filter):
    """Custom log filter for Nitrix-specific messages"""
    
    def filter(self, record):
        # Add custom filtering logic if needed
        return True

def log_bot_event(bot_name: str, event: str, details: str = None):
    """Log a bot-specific event"""
    logger = get_logger('events')
    message = f"Bot '{bot_name}': {event}"
    if details:
        message += f" - {details}"
    logger.info(message)

def log_system_event(event: str, details: str = None):
    """Log a system-wide event"""
    logger = get_logger('system')
    message = f"System: {event}"
    if details:
        message += f" - {details}"
    logger.info(message)

def create_crash_report(bot_name: str, error: Exception, context: dict = None):
    """Create a detailed crash report"""
    logger = get_logger('crashes')
    
    report = [
        f"CRASH REPORT - Bot: {bot_name}",
        f"Timestamp: {datetime.now().isoformat()}",
        f"Error: {type(error).__name__}: {str(error)}",
    ]
    
    if context:
        report.append("Context:")
        for key, value in context.items():
            report.append(f"  {key}: {value}")
    
    # Log the full report
    logger.error("\n".join(report))
    
    # Also save to crash reports directory
    crash_dir = Path('logs/crashes')
    crash_dir.mkdir(exist_ok=True)
    
    crash_file = crash_dir / f"{bot_name}_{int(datetime.now().timestamp())}.log"
    with open(crash_file, 'w') as f:
        f.write("\n".join(report))
        f.write(f"\n\nFull traceback:\n")
        import traceback
        f.write(traceback.format_exc())

def get_log_stats() -> dict:
    """Get logging statistics"""
    try:
        logs_dir = Path('logs')
        if not logs_dir.exists():
            return {'error': 'Logs directory not found'}
        
        stats = {
            'total_log_files': 0,
            'total_size_mb': 0,
            'bot_logs': {},
            'system_logs': []
        }
        
        for log_file in logs_dir.rglob('*.log'):
            file_size = log_file.stat().st_size
            stats['total_log_files'] += 1
            stats['total_size_mb'] += file_size / (1024 * 1024)
            
            if 'bots/' in str(log_file):
                bot_name = log_file.parent.parent.name
                if bot_name not in stats['bot_logs']:
                    stats['bot_logs'][bot_name] = []
                stats['bot_logs'][bot_name].append({
                    'file': log_file.name,
                    'size_mb': round(file_size / (1024 * 1024), 2)
                })
            else:
                stats['system_logs'].append({
                    'file': log_file.name,
                    'size_mb': round(file_size / (1024 * 1024), 2)
                })
        
        stats['total_size_mb'] = round(stats['total_size_mb'], 2)
        return stats
        
    except Exception as e:
        return {'error': str(e)}

def cleanup_old_logs(days_to_keep: int = 30):
    """Clean up log files older than specified days"""
    try:
        from datetime import timedelta
        cutoff_time = datetime.now() - timedelta(days=days_to_keep)
        
        logs_dir = Path('logs')
        cleaned_files = 0
        
        for log_file in logs_dir.rglob('*.log.*'):  # Rotated log files
            if log_file.stat().st_mtime < cutoff_time.timestamp():
                log_file.unlink()
                cleaned_files += 1
        
        logger = get_logger('cleanup')
        logger.info(f"Cleaned up {cleaned_files} old log files")
        
        return cleaned_files
        
    except Exception as e:
        logger = get_logger('cleanup')
        logger.error(f"Failed to clean up logs: {e}")
        return 0
