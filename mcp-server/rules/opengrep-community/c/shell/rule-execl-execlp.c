// License: MIT (c) GitLab Inc.
#include<stdio.h>

#include<stdlib.h>

#include<unistd.h>

int main() {
  FILE * p;
  char foo;
  char * args[] = {
    "./EXEC",
    NULL
  };
  // ruleid: c_shell_rule-execl-execlp
  execvp(args[0], args);
  // ruleid: c_shell_rule-execl-execlp
  execv(args[0], args);
  // ruleid: c_shell_rule-execl-execlp
  execle(args[0], args);
  // ruleid: c_shell_rule-execl-execlp
  execlp(args[0], args);
  // ruleid: c_shell_rule-execl-execlp
  execl(args[0], args);
  printf("exec family comes under unistd");

  //popen
  // ruleid: c_shell_rule-execl-execlp
  p = popen("ver", "r");

  while ((foo = fgetc(p)) != EOF)
    putchar(foo);
  pclose(p);

  return (0);
}
