// PM2 ecosystem file for local development (Windows)
// The selection server launches pipeline Node and Flask services on demand.
const path = require('path');

module.exports = {
    apps: [
        {
            name: 'selection',
            cwd: path.resolve(__dirname, 'selection'),
            script: 'server.js',
            instances: 1,
            autorestart: true,
            watch: false,
            max_memory_restart: '500M',
            log_date_format: 'YYYY-MM-DD HH:mm:ss',
            out_file: './logs/selection-out.log',
            error_file: './logs/selection-err.log',
            env: {
                NODE_ENV: 'development',
                PORT: 3000,
                AUTO_LAUNCH_PIPELINES: 'fg,fg2',
            },
        }
    ]
};
