// License: MIT (c) GitLab Inc.
#include <stdio.h>

int main() {
  char buffer[50];
  char * s = "geekyhuman";

  // ok: c_format_rule-snprintf-vsnprintf
  int j = snprintf(buffer, 5, "%s\n", s);

  // ruleid: c_format_rule-snprintf-vsnprintf
  int j = snprintf(buffer, 5, buffer, s);

  printf("string:\n%s\ncharacter count = %d\n", buffer, j);

  return 0;
}