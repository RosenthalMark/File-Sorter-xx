#!/bin/zsh
# Kill whatever is using port 5050
lsof -ti :5050 | xargs -r kill
echo "Stopped server on 5050"