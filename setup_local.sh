#!/bin/bash

# Local Development Setup Script
# Database Statistics Dashboard

set -e

echo "🚀 Setting up local development environment for Database Statistics Dashboard"
echo "=" * 80

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is required but not installed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python 3 found: $(python3 --version)${NC}"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
    echo -e "${GREEN}✅ Virtual environment created${NC}"
else
    echo -e "${YELLOW}⚠️  Virtual environment already exists${NC}"
fi

# Activate virtual environment
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "📈 Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "📚 Installing Python dependencies..."
pip install -r requirements.txt

echo -e "${GREEN}✅ Dependencies installed successfully${NC}"

# Check if .env.local exists
if [ ! -f ".env.local" ]; then
    echo -e "${RED}❌ .env.local file not found${NC}"
    echo "Please update .env.local with your database credentials"
    exit 1
fi

echo -e "${GREEN}✅ Environment configuration found${NC}"

# Check for Redis/Valkey
echo "🔍 Checking for Redis/Valkey..."
if command -v redis-server &> /dev/null; then
    echo -e "${GREEN}✅ Redis found: $(redis-server --version | head -1)${NC}"
    
    # Check if Redis is running
    if redis-cli ping &> /dev/null; then
        echo -e "${GREEN}✅ Redis is running${NC}"
    else
        echo -e "${YELLOW}⚠️  Redis is not running. Start it with: brew services start redis${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Redis not found. Install with: brew install redis${NC}"
    echo "   You can also use a remote Redis/Valkey instance"
fi

# Check for PostgreSQL
echo "🔍 Checking for PostgreSQL..."
if command -v psql &> /dev/null; then
    echo -e "${GREEN}✅ PostgreSQL found: $(psql --version)${NC}"
    
    # Check if PostgreSQL is running (on macOS with Homebrew)
    if brew services list | grep postgresql | grep started &> /dev/null; then
        echo -e "${GREEN}✅ PostgreSQL is running${NC}"
    elif pgrep -x "postgres" > /dev/null; then
        echo -e "${GREEN}✅ PostgreSQL is running${NC}"
    else
        echo -e "${YELLOW}⚠️  PostgreSQL might not be running. Start it with: brew services start postgresql${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  PostgreSQL not found. Install with: brew install postgresql${NC}"
    echo "   You can also use a remote PostgreSQL instance"
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "📝 Next steps:"
echo "1. Update .env.local with your actual database credentials"
echo "2. Create the PostgreSQL database and run schema.sql:"
echo "   createdb webapp_db_dev"
echo "   psql -d webapp_db_dev -f schema.sql"
echo ""
echo "🚀 To start the development server:"
echo "   python3 run_local.py"
echo ""
echo "🌐 The application will be available at:"
echo "   http://localhost:5000"
echo ""
echo "📊 API endpoints:"
echo "   http://localhost:5000/health"
echo "   http://localhost:5000/api/stats"
echo ""