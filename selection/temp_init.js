const { launchPipeline } = require('./server/utils/pipelines');

async function run() {
    try {
        console.log('Launching pipeline chips...');
        await launchPipeline('chips');
        console.log('chips launched.');
        console.log('Launching pipeline fg...');
        await launchPipeline('fg');
        console.log('fg launched.');
        console.log('Launching pipeline fg2...');
        await launchPipeline('fg2');
        console.log('fg2 launched.');
    } catch (error) {
        console.error('Launch failed:', error.message);
    }
}
run();
