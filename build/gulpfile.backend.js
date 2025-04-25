/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

'use strict';

const gulp = require('gulp');
const path = require('path');
const cp = require('child_process');
const util = require('./lib/util');
const task = require('./lib/task');
const fs = require('fs');
const es = require('event-stream');
const vfs = require('vinyl-fs');
const fse = require('fs-extra');

const REPO_ROOT = path.dirname(__dirname);
const BACKEND_ROOT = path.join(REPO_ROOT, 'backend');

function buildBackendTask(platform, arch) {
	return async function () {
		const pyinstaller = 'pyinstaller';
		const specFile = path.join(BACKEND_ROOT, 'backend.spec');
		const distDir = path.join(BACKEND_ROOT, 'dist');
		const buildDir = path.join(BACKEND_ROOT, 'build');

		// Clean previous builds
		await util.rimraf(distDir);
		await util.rimraf(buildDir);

		// Run PyInstaller
		const args = [
			specFile,
			'--clean',
			'--noconfirm'
		];

		return new Promise((resolve, reject) => {
			const proc = cp.spawn(pyinstaller, args, {
				cwd: BACKEND_ROOT,
				stdio: 'inherit',
				shell: true
			});

			proc.on('error', reject);
			proc.on('exit', (code) => {
				if (code === 0) {
					resolve();
				} else {
					reject(new Error(`PyInstaller exited with code ${code}`));
				}
			});
		});
	};
}

function packageBackendTask(platform, arch) {
	return async function () {
		const backendExe = platform === 'win32' ? 'backend.exe' : 'backend';
		const source = path.join(BACKEND_ROOT, 'dist', backendExe);
		const destination = path.join(REPO_ROOT, 'out-vscode', 'resources', 'app', 'backend');

		// Ensure destination directory exists
		await fse.ensureDir(path.dirname(destination));

		// Copy the file
		await fse.copy(source, path.join(destination, backendExe));
	};
}

// Define tasks for each platform
const platforms = ['win32', 'linux'];
const architectures = ['x64', 'arm64'];

platforms.forEach(platform => {
	architectures.forEach(arch => {
		const buildTask = task.define(`backend-${platform}-${arch}`, task.series(
			buildBackendTask(platform, arch),
			packageBackendTask(platform, arch)
		));
		gulp.task(buildTask);
	});
});

// Export tasks
module.exports = {
	buildBackendTask,
	packageBackendTask
};
