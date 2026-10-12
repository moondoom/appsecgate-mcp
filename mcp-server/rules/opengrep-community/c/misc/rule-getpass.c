// License: MIT (c) GitLab Inc.
#include <stdio.h>

#include <unistd.h>

int main() {
  char * password;

  // ruleid: c_misc_rule-getpass
  password = getpass("Your password: ");
  printf("Your password is '%s'\n", password);

  return (0);
}
