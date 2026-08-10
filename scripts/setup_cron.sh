#!/bin/bash
# Setup cron job for daily agent performance calculation
# Run this once on the server: bash scripts/setup_cron.sh

# Get the absolute path to the project
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(which python3)}"
MANAGE_PY="$PROJECT_DIR/manage.py"

# Create a wrapper script that runs the management command
WRAPPER="$PROJECT_DIR/scripts/run_daily_performance.sh"

cat > "$WRAPPER" << EOF
#!/bin/bash
# Daily agent performance calculation
# Runs at 23:55 every day to ensure performance data is up to date
cd "$PROJECT_DIR"
"$PYTHON_BIN" "$MANAGE_PY" calculate_daily_performance --days 1 >> "$PROJECT_DIR/logs/performance_cron.log" 2>&1
EOF

chmod +x "$WRAPPER"

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Add cron entry (runs at 23:55 every day)
CRON_LINE="55 23 * * * $WRAPPER"

# Check if already in crontab
if crontab -l 2>/dev/null | grep -q "calculate_daily_performance"; then
    echo "Cron job already exists. Updating..."
    (crontab -l 2>/dev/null | grep -v "calculate_daily_performance"; echo "$CRON_LINE") | crontab -
else
    echo "Adding cron job..."
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
fi

echo "✅ Cron job installed: $CRON_LINE"
echo "   Logs: $PROJECT_DIR/logs/performance_cron.log"
echo ""
echo "To test manually, run:"
echo "  $PYTHON_BIN $MANAGE_PY calculate_daily_performance"
echo ""
echo "To backfill missing days (skips already-recorded dates), run:"
echo "  $PYTHON_BIN $MANAGE_PY calculate_daily_performance --days 30 --backfill"
