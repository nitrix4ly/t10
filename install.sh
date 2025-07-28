#!/bin/bash

# t10 Discord Bot Manager Installation Script
# Built by Nitrix - Production-grade bot management for VPS

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
T10_DIR="/opt/t10"
T10_USER="t10"
PYTHON_VERSION="3.12"
VENV_DIR="$T10_DIR/venv"
SERVICE_FILE="/etc/systemd/system/t10.service"

print_banner() {
    echo -e "${CYAN}"
    echo "╔════════════════════════════════════════╗"
    echo "║           t10 Bot Manager              ║"
    echo "║     Discord Bot Process Manager        ║"
    echo "║         Built by Nitrix                ║"
    echo "╚════════════════════════════════════════╝"
    echo -e "${NC}"
}

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root for security reasons"
    fi
}

check_system() {
    log "Checking system requirements..."
    
    # Check OS
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        log "✓ Linux system detected"
    else
        error "This installer only supports Linux systems"
    fi
    
    # Check if running on VPS-like environment
    if command -v systemctl >/dev/null 2>&1; then
        log "✓ Systemd detected"
    else
        warn "Systemd not found - service management may be limited"
    fi
    
    # Check for required commands
    for cmd in curl wget git; do
        if ! command -v $cmd >/dev/null 2>&1; then
            error "$cmd is required but not installed"
        fi
    done
    
    log "✓ System requirements check passed"
}

install_python() {
    log "Checking Python installation..."
    
    if command -v python3.11 >/dev/null 2>&1; then
        log "✓ Python 3.11 already installed"
        return
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
        if [[ "$PYTHON_VERSION" == "3.11" ]] || [[ "$PYTHON_VERSION" == "3.12" ]]; then
            log "✓ Compatible Python version found: $PYTHON_VERSION"
            return
        fi
    fi
    
    log "Installing Python 3.11..."
    
    # Detect package manager and install Python
    if command -v apt >/dev/null 2>&1; then
        # Ubuntu/Debian
        sudo apt update
        sudo apt install -y python3.11 python3.11-venv python3.11-pip python3.11-dev
    elif command -v yum >/dev/null 2>&1; then
        # CentOS/RHEL
        sudo yum update -y
        sudo yum install -y python3.11 python3.11-pip python3.11-devel
    elif command -v dnf >/dev/null 2>&1; then
        # Fedora
        sudo dnf update -y
        sudo dnf install -y python3.11 python3.11-pip python3.11-devel
    else
        error "Unsupported package manager. Please install Python 3.11 manually"
    fi
    
    log "✓ Python 3.11 installed successfully"
}

install_docker() {
    log "Checking Docker installation..."
    
    if command -v docker >/dev/null 2>&1; then
        log "✓ Docker already installed"
        
        # Check if user is in docker group
        if groups $USER | grep -q docker; then
            log "✓ User is in docker group"
        else
            log "Adding user to docker group..."
            sudo usermod -aG docker $USER
            warn "Please log out and log back in for docker group changes to take effect"
        fi
        return
    fi
    
    log "Installing Docker..."
    
    # Install Docker using official script
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    
    # Add user to docker group
    sudo usermod -aG docker $USER
    
    # Enable and start Docker service
    sudo systemctl enable docker
    sudo systemctl start docker
    
    rm get-docker.sh
    
    log "✓ Docker installed successfully"
    warn "Please log out and log back in for docker group changes to take effect"
}

create_t10_directory() {
    log "Creating t10 directory structure..."
    
    # Create main directory
    sudo mkdir -p $T10_DIR
    sudo chown $USER:$USER $T10_DIR
    
    # Create subdirectories
    mkdir -p $T10_DIR/{bots,core,utils,data,logs}
    
    log "✓ Directory structure created"
}

download_t10() {
    log "Downloading t10 files..."
    
    cd $T10_DIR
    
    # For demo purposes, we'll create the files here
    # In production, you'd download from a repository
    
    cat > requirements.txt << 'EOF'
click>=8.1.7
aiohttp>=3.9.0
schedule>=1.2.0
docker>=6.1.3
psutil>=5.9.5
tinydb>=4.8.0
colorama>=0.4.6
pyyaml>=6.0.1
requests>=2.31.0
asyncio-subprocess>=0.1.0
watchdog>=3.0.0
EOF
    
    # Create empty __init__.py files
    touch core/__init__.py utils/__init__.py
    
    log "✓ t10 files downloaded"
}

setup_python_environment() {
    log "Setting up Python virtual environment..."
    
    cd $T10_DIR
    
    # Create virtual environment
    python3.11 -m venv $VENV_DIR
    
    # Activate and install dependencies
    source $VENV_DIR/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    log "✓ Python environment setup complete"
}

create_t10_executable() {
    log "Creating t10 executable..."
    
    # Create the main t10 script
    cat > /tmp/t10_wrapper << EOF
#!/bin/bash
# t10 Bot Manager Wrapper Script
# Ensures virtual environment activation

T10_DIR="$T10_DIR"
VENV_DIR="$VENV_DIR"

if [ ! -d "\$VENV_DIR" ]; then
    echo "Error: t10 virtual environment not found at \$VENV_DIR"
    exit 1
fi

source "\$VENV_DIR/bin/activate"
cd "\$T10_DIR"
python t10.py "\$@"
EOF
    
    # Make executable and move to /usr/local/bin
    chmod +x /tmp/t10_wrapper
    sudo mv /tmp/t10_wrapper /usr/local/bin/t10
    
    log "✓ t10 command line tool installed"
}

create_systemd_service() {
    log "Creating systemd service..."
    
    cat > /tmp/t10.service << EOF
[Unit]
Description=t10 Discord Bot Manager
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$T10_DIR
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$VENV_DIR/bin/python t10.py monitor
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    sudo mv /tmp/t10.service $SERVICE_FILE
    sudo systemctl daemon-reload
    sudo systemctl enable t10
    
    log "✓ Systemd service created and enabled"
}

setup_firewall() {
    log "Configuring firewall (if needed)..."
    
    # Check if ufw is available
    if command -v ufw >/dev/null 2>&1; then
        # Allow Docker's default bridge network
        sudo ufw allow from 172.17.0.0/16
        log "✓ Firewall configured for Docker"
    elif command -v firewall-cmd >/dev/null 2>&1; then
        # CentOS/RHEL firewall
        sudo firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=172.17.0.0/16 accept"
        sudo firewall-cmd --reload
        log "✓ Firewall configured for Docker"
    else
        warn "No recognized firewall found - manual configuration may be needed"
    fi
}

create_example_bot() {
    log "Creating example bot configuration..."
    
    EXAMPLE_DIR="$T10_DIR/bots/examplebot"
    mkdir -p $EXAMPLE_DIR/logs
    
    # Create example config
    cat > $EXAMPLE_DIR/config.json << 'EOF'
{
  "name": "examplebot",
  "dockerfile": "dockerfile",
  "env_file": "env",
  "auto_restart": true,
  "restart_on_crash": true,
  "git_auto_pull": false,
  "webhook_url": null,
  "nitrix_managed": true
}
EOF
    
    # Create example Dockerfile
    cat > $EXAMPLE_DIR/dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Run the bot
CMD ["python", "main.py"]
EOF
    
    # Create example env file
    cat > $EXAMPLE_DIR/env << 'EOF'
BOT_TOKEN=your_bot_token_here
PREFIX=!
GUILD_ID=your_guild_id_here
EOF
    
    # Create example requirements.txt
    cat > $EXAMPLE_DIR/requirements.txt << 'EOF'
discord.py>=2.3.0
python-dotenv>=1.0.0
aiohttp>=3.8.0
EOF
    
    # Create example main.py
    cat > $EXAMPLE_DIR/main.py << 'EOF'
import discord
from discord.ext import commands
import os
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/bot.log'),
        logging.StreamHandler()
    ]
)

# Bot setup
bot = commands.Bot(command_prefix=os.getenv('PREFIX', '!'), intents=discord.Intents.all())

@bot.event
async def on_ready():
    logging.info(f'{bot.user} has connected to Discord!')
    logging.info(f'Bot is in {len(bot.guilds)} guilds')

@bot.command(name='ping')
async def ping(ctx):
    """Simple ping command"""
    await ctx.send(f'Pong! Latency: {round(bot.latency * 1000)}ms')

@bot.command(name='hello')
async def hello(ctx):
    """Hello world command"""
    await ctx.send(f'Hello {ctx.author.mention}! I am managed by t10 🚀')

if __name__ == '__main__':
    token = os.getenv('BOT_TOKEN')
    if not token:
        logging.error('BOT_TOKEN not found in environment variables')
        exit(1)
    
    try:
        bot.run(token)
    except Exception as e:
        logging.error(f'Failed to start bot: {e}')
        exit(1)
EOF
    
    log "✓ Example bot created at $EXAMPLE_DIR"
}

post_install_setup() {
    log "Running post-installation setup..."
    
    # Set proper permissions
    sudo chown -R $USER:$USER $T10_DIR
    chmod +x $T10_DIR/t10.py
    
    # Initialize database
    cd $T10_DIR
    source $VENV_DIR/bin/activate
    python -c "from tinydb import TinyDB; TinyDB('data/t10.db')" 2>/dev/null || true
    
    log "✓ Post-installation setup complete"
}

print_completion() {
    echo
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Installation Complete! 🎉        ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo
    echo -e "${CYAN}🚀 t10 Discord Bot Manager is now installed!${NC}"
    echo
    echo -e "${YELLOW}Quick Start:${NC}"
    echo "  1. Edit your bot token: nano $T10_DIR/bots/examplebot/env"
    echo "  2. Start the example bot: t10 start examplebot"
    echo "  3. Check bot status: t10 status"
    echo "  4. View logs: t10 logs examplebot"
    echo
    echo -e "${YELLOW}Service Management:${NC}"
    echo "  • Start t10 monitor: sudo systemctl start t10"
    echo "  • Enable auto-start: sudo systemctl enable t10"
    echo "  • Check service status: sudo systemctl status t10"
    echo
    echo -e "${YELLOW}Common Commands:${NC}"
    echo "  • t10 add mybot          - Create new bot"
    echo "  • t10 start mybot        - Start bot"
    echo "  • t10 stop mybot         - Stop bot"
    echo "  • t10 restart mybot      - Restart bot"
    echo "  • t10 schedule mybot 2h  - Schedule restart every 2 hours"
    echo "  • t10 logs mybot -f      - Follow bot logs"
    echo "  • t10 monitor           - Start monitoring mode"
    echo
    echo -e "${YELLOW}File Locations:${NC}"
    echo "  • Installation: $T10_DIR"
    echo "  • Bot configs: $T10_DIR/bots/"
    echo "  • Logs: $T10_DIR/logs/"
    echo "  • Service file: $SERVICE_FILE"
    echo
    echo -e "${CYAN}For more information, check the README.md file${NC}"
    echo -e "${GREEN}Built with ❤️  by Nitrix${NC}"
    echo
    
    if ! groups $USER | grep -q docker; then
        echo -e "${RED}⚠️  IMPORTANT: Please log out and log back in for Docker permissions to take effect${NC}"
    fi
}

# Main installation flow
main() {
    print_banner
    
    log "Starting t10 installation..."
    
    check_root
    check_system
    install_python
    install_docker
    create_t10_directory
    download_t10
    setup_python_environment
    create_t10_executable
    create_systemd_service
    setup_firewall
    create_example_bot
    post_install_setup
    
    print_completion
}

# Uninstall function
uninstall() {
    echo -e "${YELLOW}Uninstalling t10...${NC}"
    
    # Stop and disable service
    sudo systemctl stop t10 2>/dev/null || true
    sudo systemctl disable t10 2>/dev/null || true
    
    # Remove service file
    sudo rm -f $SERVICE_FILE
    sudo systemctl daemon-reload
    
    # Remove executable
    sudo rm -f /usr/local/bin/t10
    
    # Remove installation directory
    sudo rm -rf $T10_DIR
    
    echo -e "${GREEN}✓ t10 uninstalled successfully${NC}"
}

# Handle command line arguments
case "${1:-}" in
    --uninstall)
        uninstall
        ;;
    --help|-h)
        echo "t10 Discord Bot Manager Installer"
        echo "Usage: $0 [options]"
        echo ""
        echo "Options:"
        echo "  --uninstall    Remove t10 completely"
        echo "  --help, -h     Show this help message"
        echo ""
        echo "Run without arguments to install t10"
        ;;
    "")
        main
        ;;
    *)
        error "Unknown option: $1. Use --help for usage information."
        ;;
esac
