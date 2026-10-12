// License: MIT (c) GitLab Inc.
#include <openssl/evp.h>

#include <stdio.h>

void main(void) {

  // ruleid: c_crypto_rule-EVP-des-ecb-EVP-des-cbc
  EVP_des_cbc(), EVP_des_ecb(), EVP_des_cfb(), EVP_des_ofb(), EVP_desx_cbc();

}
