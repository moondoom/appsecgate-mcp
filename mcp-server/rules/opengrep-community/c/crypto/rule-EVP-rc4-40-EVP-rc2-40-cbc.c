// License: MIT (c) GitLab Inc.
#include <openssl/evp.h>

#include <stdio.h>


void main(void) {

  // ruleid: c_crypto_rule-EVP-rc4-40-EVP-rc2-40-cbc
  EVP_rc2_40_cbc(), EVP_rc2_64_cbc(), EVP_rc4_40();

}
