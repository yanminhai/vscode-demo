

/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
require('./build/gulpfile');

import gulp from 'gulp';
import task from './build/lib/task.js';
import { buildBackendTask, packageBackendTask } from './build/gulpfile.backend.js';
//
// Load all the gulpfiles
import './build/gulpfile.vscode.js';
import './build/gulpfile.vscode.win32.js';
import './build/gulpfile.vscode.linux.js';
import './build/gulpfile.hygiene.js';
import './build/gulpfile.extensions.js';
import './build/gulpfile.compile.js';

// Modify the vscode tasks to include backend build
const platforms = ['win32', 'linux'];
const architectures = ['x64', 'arm64'];
platforms.forEach(platform => {
	architectures.forEach(arch => {
		const vscodeTask = gulp.task(`vscode-${platform}-${arch}`);
		if (vscodeTask) {
			const backendTask = task.define(`backend-${platform}-${arch}`, task.series(
				buildBackendTask(platform, arch),
				packageBackendTask(platform, arch)
			));
			gulp.task(backendTask);

			// Add backend build as a dependency to vscode build
			gulp.task(`vscode-${platform}-${arch}`, task.series(
				backendTask,
				vscodeTask
			));
		}

	});
});

