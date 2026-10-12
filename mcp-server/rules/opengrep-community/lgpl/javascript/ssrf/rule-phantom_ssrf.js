// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/ssrf/ssrf_phantomjs.js
// hash: e7a0a61
const express = require('express')
const app = express()
const port = 3000
const phantom = require('phantom');

app.get('/test', async (req, res) => {
    const instance = await phantom.create();
    const page = await instance.createPage();
    await page.on('onResourceRequested', function (requestData) {
        console.info('Requesting', requestData.url);
    });

    // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
    const status = await page.property('content', req.get('name'));

    // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
    await page.setContent(req.query.q);

    res.send('Hello World!')
})

app.post('/test2', async (req, res) => {
    const instance = await phantom.create();
    const page = await instance.createPage();
    await page.on('onResourceRequested', function (requestData) {
        console.info('Requesting', requestData.url);
    });

    // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
    const status = await page.property('content', req.query.q);

    // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
    await page.setContent(req.body);

    const express = require('express')
    const app = express()
    const port = 3000
    const phantom = require('phantom');

    app.get('/test', async (req, res) => {
        const instance = await phantom.create();
        const page = await instance.createPage();
        await page.on('onResourceRequested', function (requestData) {
            console.info('Requesting', requestData.url);
        });

        // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
        const status = await page.property('content', req.get('name'));

        // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
        await page.setContent(req.query.q);

        res.send('Hello World!')
    })

    app.post('/test2', async (req, res) => {
        const instance = await phantom.create();
        const page = await instance.createPage();
        await page.on('onResourceRequested', function (requestData) {
            console.info('Requesting', requestData.url);
        });

        // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
        const status = await page.property('content', req.query.q);

        // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
        await page.setContent(req.body);

       
        await instance.exit();

        res.send('Hello World!')
    })

    app.post('/test3', async (req, res) => {
        const instance = await phantom.create();
        const page = await instance.createPage();
        await page.on('onResourceRequested', function (requestData) {
            console.info('Requesting', requestData.url);
        });

        // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
        const status = await page.openUrl(req.params.url, {}, {});

        // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
        await page.evaluateJavaScript(req.body.script);

      
        await instance.exit();

        res.send('Hello World!')
    })


    app.listen(port, () => console.log(`Example app listening at http://localhost:${port}`))
    await instance.exit();

    res.send('Hello World!')
})

app.post('/test3', async (req, res) => {
    const instance = await phantom.create();
    const page = await instance.createPage();
    await page.on('onResourceRequested', function (requestData) {
        console.info('Requesting', requestData.url);
    });

    // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
    const status = await page.openUrl(req.params.url, {}, {});

    // ruleid: rules_lgpl_javascript_ssrf_rule-phantom-ssrf
    await page.evaluateJavaScript(req.body.script);

   

    await instance.exit();

    res.send('Hello World!')
})


app.listen(port, () => console.log(`Example app listening at http://localhost:${port}`))