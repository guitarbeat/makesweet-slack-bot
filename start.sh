#!/bin/bash
set -e

export SAVE_IMAGE_FOLDER=/makesweet/images
export GIN_MODE=release

# Start the GIF rendering server on port 8080
echo "Starting GIF server on :8080..."
/server/start &
GIF_PID=$!

# Wait for it to be ready
echo "Waiting for GIF server..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/api/docs/ > /dev/null 2>&1; then
    echo "GIF server ready!"
    break
  fi
  if ! kill -0 $GIF_PID 2>/dev/null; then
    echo "GIF server died!" && exit 1
  fi
  sleep 1
done

# Start the Slack bot (this blocks)
echo "Starting Slack bot..."
export MAKESWEET_URL=http://localhost:8080
python bot.py
