// License: GNU Lesser General Public License v3.0
// source (original): https://github.com/ajinabraham/njsscan/blob/master/tests/assets/node_source/true_positives/semantic_grep/ssrf/ssrf_wkhtmltoimage.js
// hash: e7a0a61
var wkhtmltoimage = require('wkhtmltoimage')

module.exports = function (app) {
  // http://localhost:3000/ssrf/1?url=https://www.google.com
  // You can give your collaborator url - from burp collaborator or https://app.interactsh.com/#/
  // http://localhost:3000/ssrf/1?url=http://your.collaborator.url
  app.get('/ssrf/1', (req, res) => {
    console.log(req.query.url)
    // ruleid: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
    wkhtmltoimage.generate(
      req.query.url,
      { output: 'out1.jpg' },
      function (err) {
        if (err) {
          console.error(err)
          return res.status(500).send('Error generating image')
        }
        res.send('All set')
      }
    )
  })

  // http://localhost:3000/ssrf/2?url=http://your.collaborator.url
  app.get('/ssrf/2', (req, res) => {
    console.log(req.query.url)
    url2 = req.query.url
    // ruleid: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
    wkhtmltoimage.generate(url2, { output: 'out2.jpg' }, function (err) {
      if (err) {
        console.error(err)
        return res.status(500).send('Error generating image')
      }
      res.send('All set')
    })
  })

  // Safe example - hardcoded url
  // http://localhost:3000/ssrf/3?url=https://www.youtube.com
  app.get('/ssrf/3', (req, res) => {
    url = 'http://www.google.com'
    // ok: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
    wkhtmltoimage.generate(url, { output: 'out-safe3.jpg' }, function (err) {
      if (err) {
        console.error(err)
        return res.status(500).send('Error generating image')
      }
      res.send('All set')
    })
  })

  // Safe example - hardcoded url, inline
  // http://localhost:3000/ssrf/4?url=https://www.youtube.com
  app.get('/ssrf/4', (req, res) => {
    // ok: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
    wkhtmltoimage.generate(
      'http://www.google.com',
      { output: 'out-safe4.jpg' },
      function (err) {
        if (err) {
          console.error(err)
          return res.status(500).send('Error generating image')
        }
        res.send('All set')
      }
    )
  })

  // Safe example - allowlist
  // http://localhost:3000/ssrf/5?url=https://www.youtube.com
  app.get('/ssrf/5', (req, res) => {
    allowedDomains = ['www.google.com', 'abc87654.com']
    url = req.query.url
    parsedUrl = new URL(url)

    if (allowedDomains.includes(parsedUrl.hostname)) {
      // ok: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
      wkhtmltoimage.generate(url, { output: 'out-safe5.jpg' }, function (err) {
        if (err) {
          console.error(err)
          return res.status(500).send('Error generating image')
        }
        res.send('All set')
      })
    } else {
      res.status(400).send('Invalid url')
    }
  })
}

// License: GNU Lesser General Public License v3.0
// Rule ref: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf

import express from 'express'
import w from 'wkhtmltoimage'

const router = express.Router()

// http://localhost:3000/ssrf/wkhtmltoimage/1?url=https://www.google.com
// You can give your collaborator url - from burp collaborator or https://app.interactsh.com/#/
// http://localhost:3000/ssrf/wkhtmltoimage/1?url=http://your.collaborator.url
router.route('/1').get(async (req, res) => {
  console.log(req.query.url)
  // ruleid: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
  w.generate(req.query.url, { output: 'out1.jpg' }, function (err) {
    if (err) {
      console.error(err)
      return res.status(500).send('Error generating image')
    }
    res.send('All set')
  })
})

// http://localhost:3000/ssrf/wkhtmltoimage/2?url=http://your.collaborator.url
router.route('/2').get(async (req, res) => {
  console.log(req.query.url)
  var url2 = req.query.url
  // ruleid: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
  w.generate(url2, { output: 'out2.jpg' }, function (err) {
    if (err) {
      console.error(err)
      return res.status(500).send('Error generating image')
    }
    res.send('All set')
  })
})

// Safe example - hardcoded url
// http://localhost:3000/ssrf/wkhtmltoimage/3?url=https://www.youtube.com
router.route('/3').get(async (req, res) => {
  var url = 'http://www.google.com'
  // ok: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
  w.generate(url, { output: 'out-safe3.jpg' }, function (err) {
    if (err) {
      console.error(err)
      return res.status(500).send('Error generating image')
    }
    res.send('All set')
  })
})

// Safe example - hardcoded url, inline
// http://localhost:3000/ssrf/wkhtmltoimage/4?url=https://www.youtube.com
router.route('/4').get(async (req, res) => {
  // ok: rules_lgpl_javascript_ssrf_rule-wkhtmltoimage-ssrf
  w.generate(
    'http://www.google.com',
    { output: 'out-safe4.jpg' },
    function (err) {
      if (err) {
        console.error(err)
        return res.status(500).send('Error generating image')
      }
      res.send('All set')
    }
  )
})

export default router
