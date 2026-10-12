// License: LGPL-3.0 License (c) security-code-scan
using System.Security.Cryptography;

class WeakCipherAlgorithm
{
  static void DES()
  {
    // ruleid: csharp_crypto_rule-WeakCipherAlgorithm
    DES provider = System.Security.Cryptography.DES.Create();

    // ruleid: csharp_crypto_rule-WeakCipherAlgorithm
    var provider2 = new DESCryptoServiceProvider();
  }

  static void TripleDES()
  {
    // ruleid: csharp_crypto_rule-WeakCipherAlgorithm
    TripleDES provider = System.Security.Cryptography.TripleDES.Create();

    // ruleid: csharp_crypto_rule-WeakCipherAlgorithm
    var provider2 = new TripleDESCryptoServiceProvider();
  }

  static void RC2()
  {
    // ruleid: csharp_crypto_rule-WeakCipherAlgorithm
    RC2 provider = System.Security.Cryptography.RC2.Create();

    // ruleid: csharp_crypto_rule-WeakCipherAlgorithm
    var provider2 = new RC2CryptoServiceProvider();
  }
}
