const { launchPipeline } = require('./server/utils/pipelines');

async function run() {
    try {
        console.log('Launching pipeline chips...');
        await launchPipeline('chips');
        console.log('Pipeline chips launched successfully.');

        const urls = [
            'http://localhost:5001/api/health',
            'http://localhost:3001/health'
        ];

        for (const url of urls) {
            try {
                const response = await fetch(url);
                console.log(`${url} : ${response.status}`);
            } catch (err) {
                console.log(`${url} : Error - ${err.message}`);
            }
        }
    } catch (error) {
        console.error('Launch failed:', error.message);
        process.exit(1);
    }
}

run();
