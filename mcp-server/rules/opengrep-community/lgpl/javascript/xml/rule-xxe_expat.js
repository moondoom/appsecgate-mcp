// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/xml/xxe_expat.js
// hash: e7a0a61
const express = require('express')
const app = express()
const port = 3000
const expat = require('node-expat');

app.get('/test', async (req, res) => {
    var parser = new expat.Parser('UTF-8')
    // ruleid: rules_lgpl_javascript_xml_rule-xxe-expat
    parser.parse(req.body)
    res.send('Hello World!')
})

app.get('/test1', async (req, res) => {
    var parser = new expat.Parser('UTF-8')
    // ruleid: rules_lgpl_javascript_xml_rule-xxe-expat
    parser.write(req.query.value)
    res.send('Hello World!')
})

app.get('/test2', async (req, res) => {
    var parser = new expat.Parser('UTF-8')
    // ruleid: rules_lgpl_javascript_xml_rule-xxe-expat
    var data = req.body.foo
    parser.write(data)
    res.send('Hello World!')
})

app.listen(port, () => console.log(`Example app listening at http://localhost:${port}`))