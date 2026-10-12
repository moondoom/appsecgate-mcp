// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/traversal/archive_path_overwrite.js
// hash: e7a0a61
//Ref: https://snyk.io/research/zip-slip-vulnerability
const fs = require('fs');
const unzipper = require('unzipper');
const path = require('path');

module.exports = function (app) {
    const zipPath = 'assets/zip/ZipTest.zip';
    const extractPath = 'assets/zip/ext/';
    
    // http://localhost:3000/traversal/zip-path-overwrite/1
    app.get("/traversal/zip-path-overwrite/1", async (req, res) => {
        fs.createReadStream(zipPath)
            .pipe(unzipper.Parse())
            .on('entry', entry => {
                const fileName = entry.path;
                //ruleid: rules_lgpl_javascript_traversal_rule-zip-path-overwrite
                entry.pipe(fs.createWriteStream(extractPath + fileName));
            });
    });

    // http://localhost:3000/traversal/zip-path-overwrite/2
    app.get("/traversal/zip-path-overwrite/2", async (req, res) => {
        fs.createReadStream(zipPath)
            .pipe(unzipper.Parse())
            .on('entry', entry => {
                const buffer = [];
                entry.on('data', function (chunk) {
                    buffer.push(chunk);
                });

                const fileName = entry.path;

                entry.on('end', () => {
                    const fileContent = Buffer.concat(buffer);
                    //ruleid: rules_lgpl_javascript_traversal_rule-zip-path-overwrite
                    fs.writeFileSync(extractPath + fileName, fileContent);
                });
            });

    });

    // http://localhost:3000/traversal/zip-path-overwrite/3
    app.get("/traversal/zip-path-overwrite/3", async (req, res) => {
        fs.createReadStream(zipPath)
            .pipe(unzipper.Parse())
            .on('entry', entry => {
                const buffer = [];
                entry.on('data', function (chunk) {
                    buffer.push(chunk);
                });

                const filePath = extractPath + entry.path;

                entry.on('end', () => {
                    const fileContent = Buffer.concat(buffer);
                    //ruleid: rules_lgpl_javascript_traversal_rule-zip-path-overwrite
                    fs.writeFile(filePath, fileContent, function (err) {
                        if (err) {
                            console.error(`Error writing file ${filePath}:`, err);
                        } else {
                            console.log(`Extracted ${extractPath + entry.path}`);
                        }
                    });
                });
            });
    });

    // http://localhost:3000/traversal/zip-path-overwrite/safe/1
    app.get("/traversal/zip-path-overwrite/safe/1", async (req, res) => {
        const indexArray = ["helloText.txt"]

        fs.createReadStream(zipPath)
            .pipe(unzipper.Parse())
            .on('entry', entry => {
                if (indexArray.indexOf(entry.path) != -1) {
                    const buffer = [];
                    entry.on('data', function (chunk) {
                        buffer.push(chunk);
                    });

                    const filePath = extractPath + entry.path;

                    entry.on('end', () => {
                        const fileContent = Buffer.concat(buffer);
                        //ok: rules_lgpl_javascript_traversal_rule-zip-path-overwrite
                        fs.writeFile(filePath, fileContent, function (err) {
                            if (err) {
                                console.error(`Error writing file ${filePath}:`, err);
                            } else {
                                console.log(`Extracted ${extractPath + entry.path}`);
                            }
                        });
                    });
                }
            });
    });

    // http://localhost:3000/traversal/zip-path-overwrite/safe/2
    app.get("/traversal/zip-path-overwrite/safe/2", async (req, res) => {
        fs.createReadStream(zipPath)
            .pipe(unzipper.Parse())
            .on('entry', entry => {
                const directory = 'assets/zip/ext/';
                
                //ok: rules_lgpl_javascript_traversal_rule-zip-path-overwrite
                entry.pipe(fs.createWriteStream(path.join(directory, path.basename(entry.path))));
            });
    });
}