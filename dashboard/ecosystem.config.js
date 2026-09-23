module.exports = {
  apps: [{
    name: "jarvis-dashboard",
    // Absolute path required: pm2 on Windows mis-resolves relative script
    // paths with cwd (runs node with the directory as the module → MODULE_NOT_FOUND,
    // then can't find .next because it starts in the wrong working directory).
    // This bypasses the `pnpm run start` cmd wrapper that hangs at "Starting…".
    script: "C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\dashboard\\node_modules\\next\\dist\\bin\\next",
    args: "start --port 3010",
    cwd: "C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\dashboard",
    interpreter: "node",
    autorestart: true,
    max_restarts: 20,
    restart_delay: 2000,
    env: {
      NODE_ENV: "production"
    }
  }]
}
