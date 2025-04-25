/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

const gulp = require('gulp');
const path = require('path');
const fs = require('fs');
const util = require('./lib/util');
const task = require('./lib/task');
const { getVersion } = require('./lib/getVersion');
const { readISODate } = require('./lib/date');
const { inlineMeta } = require('./lib/inlineMeta');
const { getProductionDependencies } = require('./lib/dependencies');
const { config } = require('./lib/electron');
const { createAsar } = require('./lib/asar');
const { promisify } = require('util');
const { glob } = require('glob');
const { buildBackendTask, packageBackendTask } = require('./gulpfile.backend');
const crypto = require('crypto');
const i18n = require('./lib/i18n');
const es = require('event-stream');
const { hygiene } = require('./hygiene');

const repoPath = path.dirname(__dirname);
const commit = getVersion(repoPath);
const pkg = JSON.parse(fs.readFileSync(path.join(repoPath, 'package.json'), 'utf8'));
const product = JSON.parse(fs.readFileSync(path.join(repoPath, 'product.json'), 'utf8'));

/**
 * @param {string} actualPath
 */
function checkPackageJSON(actualPath) {
	const actual = JSON.parse(fs.readFileSync(path.join(__dirname, '..', actualPath), 'utf8'));
	const rootPackageJSON = JSON.parse(fs.readFileSync(path.join(repoPath, 'package.json'), 'utf8'));
	const checkIncluded = (set1, set2) => {
		for (const depName in set1) {
			const depVersion = set1[depName];
			const rootDepVersion = set2[depName];
			if (!rootDepVersion) {
				// missing in root is allowed
				continue;
			}
			if (depVersion !== rootDepVersion) {
				this.emit(
					'error',
					`The dependency ${depName} in '${actualPath}' (${depVersion}) is different than in the root package.json (${rootDepVersion})`
				);
			}
		}
	};

	checkIncluded(actual.dependencies, rootPackageJSON.dependencies);
	checkIncluded(actual.devDependencies, rootPackageJSON.devDependencies);
}

const checkPackageJSONTask = task.define('check-package-json', () => {
	return gulp.src('package.json').pipe(
		es.through(function () {
			checkPackageJSON.call(this, 'remote/package.json');
			checkPackageJSON.call(this, 'remote/web/package.json');
			checkPackageJSON.call(this, 'build/package.json');
		})
	);
});
gulp.task(checkPackageJSONTask);

const hygieneTask = task.define('hygiene', task.series(checkPackageJSONTask, () => hygiene(undefined, false)));
gulp.task(hygieneTask);
