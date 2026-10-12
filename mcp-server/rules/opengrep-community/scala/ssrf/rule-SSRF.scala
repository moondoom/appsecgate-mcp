// License: LGPL-3.0 License (c) find-sec-bugs
package ssrf

import java.io.IOException
import java.net._

object SSRF {
  @throws[IOException]
  def testURL(url: String): Unit = {
    // ruleid: scala_ssrf_rule-SSRF
    new URL(url).openConnection.connect()
    // ruleid: scala_ssrf_rule-SSRF
    new URL("http://safe.com").openConnection(new Proxy(Proxy.Type.HTTP, new InetSocketAddress(url, 8080))).connect()
    // ruleid: scala_ssrf_rule-SSRF
    new URL(url).openConnection.getInputStream()
    // ruleid: scala_ssrf_rule-SSRF
    new URL(url).openConnection.getLastModified()
    // ruleid: scala_ssrf_rule-SSRF
    new URL(url).openStream()
    // ruleid: scala_ssrf_rule-SSRF
    new URL(url).getContent()
    // ruleid: scala_ssrf_rule-SSRF
    new URL(url).getContent(new Array(0))
  }

  @throws[IOException]
  @throws[URISyntaxException]
  def testURI(url: String): Unit = {
    // ruleid: scala_ssrf_rule-SSRF
    new URI(url).toURL.openConnection.connect
  }
}
