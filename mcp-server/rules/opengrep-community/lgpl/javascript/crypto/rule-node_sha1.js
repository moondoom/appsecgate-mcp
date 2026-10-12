// License: GNU Lesser General Public License v3.0
// Rule ref: rules_lgpl_javascript_crypto_rule-node-sha1

class TestSHA1Hash {
  async run () {
    console.log('Running TestSHA1Hash')
    generateSHA1Hash_crypto()
    generateSHA1Hash_crypto_js()
    generateSHA1Hash_hash_js()
    generateSHA1Hash_create_hash()
    generateSHA1Hash_node_forge()
    generateSHA1Hash_jshashes()
    generateSHA1Hash_jssha()
    generateSHA1Hash_sha_js()
    generateSHA1Hash_webcrypto()
    generateSHA1Hash_bcrypto()
    generateSHA1Hash_sjcl()
    generateSHA1Hash_sha1()
    generateSHA1Hash_js_sha1()
    testTrueNegatives()
    console.log('Stopping TestSHA1Hash')
  }
}

function generateSHA1Hash_crypto () {
  const crypto = require('crypto')
  const data = 'hello world!'
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash1 = crypto.createHash('sha1').update(data).digest('hex')
  console.log('Using crypto library : ' + hash1)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash2 = require('crypto')
    .createHash('sha1')
    .update('hello world!')
    .digest('hex')
  console.log('Using crypto library - part 2: ' + hash2)

  const hash2a = require('crypto')

  const a = hash2a.createHash('sha1')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const b = a.update('hello world!').digest('hex')
  console.log('Using crypto library - part 3: ' + b)
}

function generateSHA1Hash_crypto_js () {
  const CryptoJS = require('crypto-js')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash3 = CryptoJS.SHA1('hello world!').toString()
  console.log('Using crypto-js library : ' + hash3)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash3a = require('crypto-js').SHA1('hello world!').toString()
  console.log('Using crypto-js library - part 2: ' + hash3a)
}

function generateSHA1Hash_hash_js () {
  const hash = require('hash.js')
  const data = 'hello world!'
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash4 = hash.sha1().update(data).digest('hex')
  console.log('Using hash.js library : ' + hash4)

  const a = require('hash.js').sha1()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash4a = a.update('hello world!').digest('hex')
  console.log('Using hash.js library - part 2:' + hash4a)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash4b = require('hash.js').sha1().update('hello world!').digest('hex')
  console.log('Using hash.js library - part 3:' + hash4b)
}

function generateSHA1Hash_node_forge () {
  const forge = require('node-forge')
  const val = forge.md.sha1.create()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  val.update('hello world!')
  const hash6 = val.digest().toHex()
  console.log('Using node-forge library : ' + hash6)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const qwe = require('node-forge').md.sha1.create().update('hello world!')
  const hash6a = qwe.digest().toHex()
  console.log('Using node-forge library - part 2: ' + hash6a)

  const eee = require('node-forge').md.sha1.create()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  eee.update('hello world!')
  const hash6b = qwe.digest().toHex()
  console.log('Using node-forge library - part 3: ' + hash6b)
}

function generateSHA1Hash_jshashes () {
  const Hashes = require('jshashes')
  const val = new Hashes.SHA1()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash7 = val.hex('hello world!')
  console.log('Using jshashes library : ' + hash7)
}

function generateSHA1Hash_create_hash () {
  const createHash = require('create-hash')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash9 = createHash('sha1').update('hello world!').digest('hex')
  console.log('Using create-hash library : ' + hash9)
}

function generateSHA1Hash_jssha () {
  const jsSHA = require('jssha')
  const shaObj = new jsSHA('SHA-1', 'TEXT')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  shaObj.update('hello world!')
  const hash = shaObj.getHash('HEX')
  console.log('Using jssha library : ' + hash)

  const jsSHA2 = require('jssha')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash2 = new jsSHA2('SHA-1', 'TEXT')
    .update('hello world!')
    .getHash('HEX')

  console.log('Using jssha library - part 2: ' + hash2)
}

function generateSHA1Hash_sha_js () {
  const x = require('sha.js')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash = x('sha1').update('hello world!').digest('hex')
  console.log('Using sha.js library : ' + hash)

  const sha1a = require('sha.js')
  const a = sha1a('sha1')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash2 = a.update('hello world!').digest('hex')
  console.log('Using sha.js library - part 2:' + hash2)
}

function generateSHA1Hash_webcrypto () {
  const crypto = require('crypto').webcrypto
  async function sha1Hash (data) {
    // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
    const hashBuffer = await crypto.subtle.digest(
      'SHA-1',
      new TextEncoder().encode(data)
    )
    return Array.from(new Uint8Array(hashBuffer))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('')
  }
  sha1Hash('hello world!')
    .then(hash => console.log('Using webcrypto :' + hash))
    .catch(console.error)
}

function generateSHA1Hash_bcrypto () {
  const bcrypto = require('bcrypto')
  const data = Buffer.from('hello world!')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash = bcrypto.SHA1.digest(data).toString('hex')
  console.log('Using bcrypto library : ' + hash)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash2 = require('bcrypto').SHA1.digest(data).toString('hex')
  console.log('Using bcrypto library - part 2 : ' + hash2)

  const a = require('bcrypto').SHA1
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash3 = a.digest(data).toString('hex')
  console.log('Using bcrypto library - part 3 : ' + hash3)
}

function generateSHA1Hash_sjcl () {
  const sjcl = require('../sjcl.js')
  const data = sjcl.hash.sha1.hash('hello world!')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash1 = sjcl.codec.hex.fromBits(data)
  console.log('Using sjcl library : ' + hash1)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash2 = require('../sjcl.js').codec.hex.fromBits(
    sjcl.hash.sha1.hash('hello world!')
  )
  console.log('Using sjcl library - part 2: ' + hash2)
}

function generateSHA1Hash_sha1 () {
  const sha1 = require('sha1')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash = sha1('hello world!')
  console.log('Using sha1 library : ' + hash)
}

function generateSHA1Hash_js_sha1 () {
  const sha1 = require('js-sha1')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash = sha1('hello world!')
  console.log('Using js-sha1 library : ' + hash)
}

function testTrueNegatives () {
  const crypto = require('crypto')
  // ok: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash = crypto.createHash('sha256').update('hello world!').digest('hex')
  console.log(hash)

  const x = require('sha.js')
  // ok: rules_lgpl_javascript_crypto_rule-node-sha1
  const hash2 = x('sha256').update('hello world!').digest('hex')
  console.log('Using sha.js library : ' + hash2)

  const forge = require('node-forge')
  const val = forge.md.sha256.create()
  // ok: rules_lgpl_javascript_crypto_rule-node-sha1
  val.update('hello world!')
  const hash6 = val.digest().toHex()
  console.log('Using node-forge library : ' + hash6)
}

module.exports = TestSHA1Hash
