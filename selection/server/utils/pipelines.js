'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..');
const PYTHON_EXE = process.env.PYTHON_EXE || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');

const SELECTION_PORT = 3000;
const CHIPS_NODE_PORT = 3001;
const CHIPS_FLASK_PORT = 5001;
const FG_NODE_PORT = 3002;
const FG_FLASK_PORT = 5000;
const FG2_NODE_PORT = 3003;
const FG2_FLASK_PORT = 5003;

const CHIPS_NODE_DIR = path.join(PROJECT_ROOT, 'CHiPS', '05_webui', 'nodejs');
const FG_NODE_DIR = path.join(PROJECT_ROOT, 'FG', '05_webui', 'nodejs');
const FG2_NODE_DIR = path.join(PROJECT_ROOT, 'FG-2', '05_webui', 'nodejs');
const CHIPS_FLASK_DIR = path.join(PROJECT_ROOT, 'CHiPS', '05_webui');
const FG_FLASK_DIR = path.join(PROJECT_ROOT, 'FG', '05_webui');
const FG2_FLASK_DIR = path.join(PROJECT_ROOT, 'FG-2', '05_webui');

const CHIPS_QDRANT_LOCAL_PATH = path.join(PROJECT_ROOT, 'CHiPS', '04_embeddings_and_kg', 'db', 'qdrant_local_chips');
const FG_QDRANT_LOCAL_PATH = path.join(PROJECT_ROOT, 'FG', '04_embeddings_and_kg', 'db', 'qdrant_local_fg');
const FG2_QDRANT_LOCAL_PATH = path.join(PROJECT_ROOT, 'FG-2', '04_embeddings_and_kg', 'db', 'qdrant_local_fg2');

const CHIPS_SERVER_PATH = path.join(CHIPS_NODE_DIR, 'server.js');
const FG_SERVER_PATH = path.join(FG_NODE_DIR, 'server.js');
const FG2_SERVER_PATH = path.join(FG2_NODE_DIR, 'server.js');
const CHIPS_APP_PATH = path.join(PROJECT_ROOT, 'CHiPS', '05_webui', 'app.py');
const FG_APP_PATH = path.join(PROJECT_ROOT, 'FG', '05_webui', 'app.py');
const FG2_APP_PATH = path.join(PROJECT_ROOT, 'FG-2', '05_webui', 'app.py');

const PIPELINES = {
    chips: {
        name: 'chips',
        nodePort: CHIPS_NODE_PORT,
        flaskPort: CHIPS_FLASK_PORT,
        cwd: CHIPS_NODE_DIR,
        flaskCwd: CHIPS_FLASK_DIR,
        serverPath: CHIPS_SERVER_PATH,
        appPath: CHIPS_APP_PATH,
        qdrantLocalPath: CHIPS_QDRANT_LOCAL_PATH,
    },
    fg: {
        name: 'fg',
        nodePort: FG_NODE_PORT,
        flaskPort: FG_FLASK_PORT,
        cwd: FG_NODE_DIR,
        flaskCwd: FG_FLASK_DIR,
        serverPath: FG_SERVER_PATH,
        appPath: FG_APP_PATH,
        qdrantLocalPath: FG_QDRANT_LOCAL_PATH,
    },
    fg2: {
        name: 'fg2',
        nodePort: FG2_NODE_PORT,
        flaskPort: FG2_FLASK_PORT,
        cwd: FG2_NODE_DIR,
        flaskCwd: FG2_FLASK_DIR,
        serverPath: FG2_SERVER_PATH,
        appPath: FG2_APP_PATH,
        qdrantLocalPath: FG2_QDRANT_LOCAL_PATH,
    },
};
PIPELINES.finance = PIPELINES.fg;

const PORTS = {
    selection: SELECTION_PORT,
    chips: CHIPS_NODE_PORT,
    fg: FG_NODE_PORT,
    finance: FG_NODE_PORT,
    fg2: FG2_NODE_PORT,
};

const FLASK_PORTS = {
    chips: CHIPS_FLASK_PORT,
    fg: FG_FLASK_PORT,
    finance: FG_FLASK_PORT,
    fg2: FG2_FLASK_PORT,
};

const PATHS = {
    selectionUrl: `http://localhost:${SELECTION_PORT}/select`,
    chipsServer: CHIPS_SERVER_PATH,
    fgServer: FG_SERVER_PATH,
    fg2Server: FG2_SERVER_PATH,
    chipsApp: CHIPS_APP_PATH,
    fgApp: FG_APP_PATH,
    fg2App: FG2_APP_PATH,
};

const runningProcesses = new Map();

function getPipelineConfig(pipelineName) {
    return PIPELINES[pipelineName] || null;
}

function isServerAlive(port, healthPath = '/health') {
    return new Promise((resolve) => {
        const req = http.get(`http://localhost:${port}${healthPath}`, (res) => {
            resolve(res.statusCode === 200);
        });
        req.on('error', () => resolve(false));
        req.setTimeout(2000, () => {
            req.destroy();
            resolve(false);
        });
    });
}

async function waitForServer(port, timeout = 30000, healthPath = '/health') {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeout) {
        if (await isServerAlive(port, healthPath)) {
            return true;
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
    }
    return false;
}

function spawnNodePipeline(pipeline) {
    const logStream = fs.createWriteStream(path.join(pipeline.cwd, 'server.log'), { flags: 'a' });
    const child = spawn('node', ['server.js'], {
        cwd: pipeline.cwd,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
            ...process.env,
            PORT: String(pipeline.nodePort),
            FLASK_PORT: String(pipeline.flaskPort),
            FLASK_URL: `http://localhost:${pipeline.flaskPort}`,
        },
    });

    if (child.stdout) {
        child.stdout.on('data', (data) => {
            logStream.write(data);
        });
    }

    if (child.stderr) {
        child.stderr.on('data', (data) => {
            logStream.write(data);
        });
    }

    child.on('exit', (code, signal) => {
        logStream.write(`[launcher] exited with code ${code} (signal: ${signal})\n`);
        logStream.end();
        const running = runningProcesses.get(pipeline.name);
        if (running?.node === child) {
            running.node = null;
        }
        if (running && !running.node && !running.flask) {
            runningProcesses.delete(pipeline.name);
        }
    });

    child.on('error', (err) => {
        logStream.write(`[launcher] failed to spawn: ${err.message}\n`);
        logStream.end();
        const running = runningProcesses.get(pipeline.name);
        if (running?.node === child) {
            running.node = null;
        }
        if (running && !running.node && !running.flask) {
            runningProcesses.delete(pipeline.name);
        }
    });

    return child;
}

function spawnFlaskPipeline(pipeline) {
    if (pipeline.qdrantLocalPath) {
        fs.mkdirSync(pipeline.qdrantLocalPath, { recursive: true });
    }

    const logStream = fs.createWriteStream(path.join(pipeline.flaskCwd, 'flask.log'), { flags: 'a' });
    const child = spawn(PYTHON_EXE, ['app.py'], {
        cwd: pipeline.flaskCwd,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
            ...process.env,
            FLASK_HOST: '0.0.0.0',
            FLASK_PORT: String(pipeline.flaskPort),
            CHIPPY_QDRANT_LOCAL_PATH: pipeline.qdrantLocalPath,
            PYTHONIOENCODING: 'utf-8',
            PYTHONUTF8: '1',
        },
    });

    if (child.stdout) {
        child.stdout.on('data', (data) => {
            logStream.write(data);
        });
    }

    if (child.stderr) {
        child.stderr.on('data', (data) => {
            logStream.write(data);
        });
    }

    child.on('exit', (code, signal) => {
        logStream.write(`[launcher] exited with code ${code} (signal: ${signal})\n`);
        logStream.end();
        const running = runningProcesses.get(pipeline.name);
        if (running?.flask === child) {
            running.flask = null;
        }
        if (running && !running.node && !running.flask) {
            runningProcesses.delete(pipeline.name);
        }
    });

    child.on('error', (err) => {
        logStream.write(`[launcher] failed to spawn: ${err.message}\n`);
        logStream.end();
        const running = runningProcesses.get(pipeline.name);
        if (running?.flask === child) {
            running.flask = null;
        }
        if (running && !running.node && !running.flask) {
            runningProcesses.delete(pipeline.name);
        }
    });

    return child;
}

async function launchPipeline(pipelineName) {
    const pipeline = getPipelineConfig(pipelineName);
    if (!pipeline) {
        return { success: false, error: `Unknown pipeline: ${pipelineName}` };
    }
    const processKey = pipeline.name;

    const running = runningProcesses.get(processKey);
    if (running?.node && running?.flask && !running.node.killed && !running.flask.killed) {
        return { success: true, url: `http://localhost:${pipeline.nodePort}` };
    }

    if (running) {
        running.node?.kill('SIGTERM');
        running.flask?.kill('SIGTERM');
        runningProcesses.delete(processKey);
    }

    const flaskChild = spawnFlaskPipeline(pipeline);
    const flaskReady = await waitForServer(pipeline.flaskPort, 180000, '/api/health');
    if (!flaskReady) {
        flaskChild.kill('SIGTERM');
        runningProcesses.delete(processKey);
        return { success: false, error: 'Flask backend failed to start' };
    }

    const nodeChild = spawnNodePipeline(pipeline);
    runningProcesses.set(processKey, { node: nodeChild, flask: flaskChild });

    const ready = await waitForServer(pipeline.nodePort, 30000);
    if (!ready) {
        nodeChild.kill('SIGTERM');
        flaskChild.kill('SIGTERM');
        runningProcesses.delete(processKey);
        return { success: false, error: 'Pipeline failed to start' };
    }

    return { success: true, url: `http://localhost:${pipeline.nodePort}` };
}

function killAllPipelines() {
    for (const running of runningProcesses.values()) {
        running.node?.kill('SIGTERM');
        running.flask?.kill('SIGTERM');
    }
    runningProcesses.clear();
}

module.exports = {
    PROJECT_ROOT,
    PORTS,
    FLASK_PORTS,
    PATHS,
    PIPELINES,
    SELECTION_PORT,
    CHIPS_NODE_PORT,
    CHIPS_FLASK_PORT,
    FG_NODE_PORT,
    FG2_NODE_PORT,
    FG_FLASK_PORT,
    FG2_FLASK_PORT,
    launchPipeline,
    killAllPipelines,
    runningProcesses,
};
