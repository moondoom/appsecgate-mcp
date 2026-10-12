// License: MIT (c) GitLab Inc.
#include <stdio.h>

#include <stdlib.h>

#include <string.h>

int main() {
  int valone, valtwo;
  char string[20];

  strcpy(string, "123321");
  // ruleid: c_integer_rule-atoi-atol
  valone = atoi(string);
  // ruleid: c_integer_rule-atoi-atol
  valtwo = atol(string);

  return (0);
}
