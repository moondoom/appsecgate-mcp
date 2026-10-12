// License: GNU Lesser General Public License v3.0

const abc = require('md5')

class TestMD5Hash {
  async run () {
    console.log('Running TestMD5Hash')
    generateMD5Hash_blueimp_md5()
    generateMD5Hash_crypto()
    generateMD5Hash_crypto_js()
    generateMD5Hash_js_md5()
    generateMD5Hash_jshashes()
    generateMD5Hash_md5()
    generateMD5Hash_node_forge()
    generateMD5Hash_create_hash()
    console.log('Stopping TestMD5Hash')
  }
}

function generateMD5Hash_crypto () {
  const crypto = require('crypto')
  const data = 'hello world!'
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash1 = crypto.createHash('md5').update(data).digest('hex')
  console.log('Using crypto library : ' + hash1)

  // ruleid:rules_lgpl_javascript_crypto_rule-node-md5
  const hash2 = require('crypto')
    .createHash('md5')
    .update('hello world!')
    .digest('hex')
  console.log('Using crypto library - part 2: ' + hash2)

  const hash2a = require('crypto')

  const a = hash2a.createHash('md5')
  // ruleid:rules_lgpl_javascript_crypto_rule-node-md5
  const b = a.update('hello world!').digest('hex')
  console.log('Using crypto library - part 3: ' + b)
}

function generateMD5Hash_crypto_js () {
  const CryptoJS = require('crypto-js')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash3 = CryptoJS.MD5('hello world!').toString()
  console.log('Using crypto-js library : ' + hash3)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash3a = require('crypto-js').MD5('hello world!').toString()
  console.log('Using crypto-js library - part 2: ' + hash3a)
}

function generateMD5Hash_md5 () {
  const def = require('md5')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash4 = def('hello world!')
  console.log('Using md5 library : ' + hash4)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash4a = abc('hello world!')
  console.log('Using md5 library - part 2: ' + hash4a)
}

function generateMD5Hash_blueimp_md5 () {
  const m = require('blueimp-md5')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash5 = m('hello world!')
  console.log('Using blueimp-md5 library : ' + hash5)
}

function generateMD5Hash_node_forge () {
  const forge = require('node-forge')
  const md5 = forge.md.md5.create()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  md5.update('hello world!')
  const hash6 = md5.digest().toHex()
  console.log('Using node-forge library : ' + hash6)

  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const qwe = require('node-forge').md.md5.create().update('hello world!')
  const hash6a = qwe.digest().toHex()
  console.log('Using node-forge library - part 2: ' + hash6a)

  const eee = require('node-forge').md.md5.create()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  eee.update('hello world!')
  const hash6b = qwe.digest().toHex()
  console.log('Using node-forge library - part 3: ' + hash6b)
}

function generateMD5Hash_jshashes () {
  const Hashes = require('jshashes')
  const MD5 = new Hashes.MD5()
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash7 = MD5.hex('hello world!')
  console.log('Using jshashes library : ' + hash7)
}

function generateMD5Hash_js_md5 () {
  const md5ww = require('js-md5')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash8 = md5ww('hello world!')
  console.log('Using js-md5 library : ' + hash8)
}

function generateMD5Hash_create_hash () {
  const createHash = require('create-hash')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash9 = createHash('md5').update('hello world!').digest('hex')
  console.log('Using create-hash library : ' + hash9)

  const xyz = require('create-hash')

  const a = xyz('md5')
  // ruleid: rules_lgpl_javascript_crypto_rule-node-md5
  const hash9a = a.update('hello world!').digest('hex')
  console.log('Using create-hash library : ' + hash9a)
}

module.exports = TestMD5Hash
