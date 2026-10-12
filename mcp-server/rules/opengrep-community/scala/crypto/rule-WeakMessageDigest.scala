// License: LGPL-3.0 License (c) find-sec-bugs
package crypto

import java.security.MessageDigest
import java.security.NoSuchAlgorithmException
import java.security.NoSuchProviderException
import java.security.Provider
import java.security.Signature


object WeakMessageDigest {
  @throws[NoSuchProviderException]
  @throws[NoSuchAlgorithmException]
  def weakDigestMoreSig(): Unit = {
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD5", "SUN")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD4", "SUN")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD2", "SUN")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD5")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD4")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD2")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD5", new WeakMessageDigest.ExampleProvider)
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD4", new WeakMessageDigest.ExampleProvider)
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("MD2", new WeakMessageDigest.ExampleProvider)
    MessageDigest.getInstance("SHA", "SUN")
    MessageDigest.getInstance("SHA", new WeakMessageDigest.ExampleProvider)
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("SHA1", "SUN")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("SHA1", new WeakMessageDigest.ExampleProvider)
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("SHA-1", "SUN")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    MessageDigest.getInstance("SHA-1", new WeakMessageDigest.ExampleProvider)
    MessageDigest.getInstance("sha-384", "SUN") //OK!

    MessageDigest.getInstance("SHA-512", "SUN")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    Signature.getInstance("MD5withRSA")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    Signature.getInstance("MD2withDSA", "X")
    // ruleid: scala_crypto_rule-WeakMessageDigest
    Signature.getInstance("SHA1withRSA", new WeakMessageDigest.ExampleProvider)
    Signature.getInstance("SHA256withRSA") //OK

    Signature.getInstance("uncommon name", "")
  }

  private class ExampleProvider(info: String) extends Provider("example", 0.0, info) {
    def this() {
      this("example")
    }
  }
}
