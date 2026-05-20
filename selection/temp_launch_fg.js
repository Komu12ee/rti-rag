const { launchPipeline } = require('./server/utils/pipelines');

async function run() {
    const pipelines = ['fg', 'fg2'];
    const healthMap = {
        'fg': ['http://localhost:5002/api/health', 'http://localhost:3002/health'],
        'fg2': ['http://localhost:5003/api/health', 'http://localhost:3003/health']
    };

    for (const pipeline of pipelines) {
        try {
            console.log(`Launching pipeline ${pipeline}...`);
            await launchPipeline(pipeline);
            console.log(`Pipeline ${pipeline} launched successfully.`);

            for (const url of healthMap[pipeline]) {
                try {
                    const response = await fetch(url);
                    console.log(`${url} : ${response.status}`);
                } catch (err) {
                    console.log(`${url} : Error - ${err.message}`);
                }
            }
        } catch (error) {
            console.error(`Launch failed for ${pipeline}:`, error.message);
        }
        console.log('---');
    }
}

run();
