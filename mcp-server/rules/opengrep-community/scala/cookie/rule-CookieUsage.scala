// License: LGPL-3.0 License (c) find-sec-bugs
package cookie

import javax.servlet.ServletException
import javax.servlet.http.Cookie
import javax.servlet.http.HttpServletRequest
import javax.servlet.http.HttpServletResponse
import java.io.IOException

class CookieUsage {
  @Override
  @throws[ServletException]
  @throws[IOException]
  protected def doGet(req: HttpServletRequest, resp: HttpServletResponse): Unit = {
    for (cookie <- req.getCookies) {
      // ruleid: scala_cookie_rule-CookieUsage
      cookie.getName
      // ruleid: scala_cookie_rule-CookieUsage
      cookie.getValue
      // ruleid: scala_cookie_rule-CookieUsage
      cookie.getPath
    }
  }

  def getCookieName(req: HttpServletRequest) = {
    val c: Cookie = req.getCookies.head
    c.getName
  }
}
