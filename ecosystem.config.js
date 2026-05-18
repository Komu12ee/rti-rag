// PM2 ecosystem file for local development (Windows)
// Useful commands:
//   pm2 start ecosystem.config.js --env production
//   pm2 logs
//   pm2 restart all
//   pm2 save
//   pm2 startup

const path = require('path');

module.exports = {
    apps: [
        // Selection server: pipeline selection UI (Express) on port 3000
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
            merge_logs: false,
            env: {
                NODE_ENV: 'development',
                PORT: 3000,
            },
            env_production: {
                NODE_ENV: 'production',
                PORT: 3000,
            },
        },

        // CHiPS pipeline server: CHiPS UI (Express) on port 3001
        {
            name: 'chips',
            cwd: path.resolve(__dirname, 'CHiPS', '05_webui', 'nodejs'),
            script: 'server.js',
            instances: 1,
            autorestart: true,
            watch: false,
            max_memory_restart: '500M',
            log_date_format: 'YYYY-MM-DD HH:mm:ss',
            out_file: './logs/chips-out.log',
            error_file: './logs/chips-err.log',
            merge_logs: false,
            env: {
                NODE_ENV: 'development',
                PORT: 3001,
                FLASK_PORT: 5001,
            },
            env_production: {
                NODE_ENV: 'production',
                PORT: 3001,
                FLASK_PORT: 5001,
            },
        },

        // FG pipeline server: Finance/GAD UI (Express) on port 3002
        {
            name: 'fg',
            cwd: path.resolve(__dirname, 'FG', '05_webui', 'nodejs'),
            script: 'server.js',
            instances: 1,
            autorestart: true,
            watch: false,
            max_memory_restart: '500M',
            log_date_format: 'YYYY-MM-DD HH:mm:ss',
            out_file: './logs/fg-out.log',
            error_file: './logs/fg-err.log',
            merge_logs: false,
            env: {
                NODE_ENV: 'development',
                PORT: 3002,
                FLASK_PORT: 5002,
            },
            env_production: {
                NODE_ENV: 'production',
                PORT: 3002,
                FLASK_PORT: 5002,
            },
        },
        // FG-2 pipeline server: Alternate Finance/GAD UI (Express) on port 3003
        {
            name: 'fg2',
            cwd: path.resolve(__dirname, 'FG-2', '05_webui', 'nodejs'),
            script: 'server.js',
            instances: 1,
            autorestart: true,
            watch: false,
            max_memory_restart: '500M',
            log_date_format: 'YYYY-MM-DD HH:mm:ss',
            out_file: './logs/fg2-out.log',
            error_file: './logs/fg2-err.log',
            merge_logs: false,
            env: {
                NODE_ENV: 'development',
                PORT: 3003,
                FLASK_PORT: 5003,
            },
            env_production: {
                NODE_ENV: 'production',
                PORT: 3003,
                FLASK_PORT: 5003,
            },
        },
    ],
};
