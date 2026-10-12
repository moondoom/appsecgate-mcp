// License: MIT (c) GitLab Inc.
#include <stdio.h>

void main() {
  printf("Hello!");
}

int demo(char * a, char * b) {
  // ok: c_format_rule-syslog
  syslog(LOG_ERR, "cannot open config file (%s): %s", filename, strerror(errno))
  // ok: c_format_rule-syslog
  syslog(LOG_CRIT, "malloc() failed");
  // ruleid: c_format_rule-syslog
  syslog(LOG_ERR, attacker_string);
}
