// License: LGPL-3.0 License (c) find-sec-bugs
// scaffold: dependencies=com.amazonaws.aws-java-sdk-simpledb@1.12.187
package inject

import javax.servlet.http.HttpServletRequest
import java.util.ResourceBundle
import java.util.function.Supplier
import java.util.logging._


object CLRFInjectionLogs {
  var req = null
}

class CLRFInjectionLogs {
  def javaUtilLogging(req: HttpServletRequest): Unit = {
    val tainted = req.getParameter("test")
    val safe = "safe"
    val logger = Logger.getLogger(classOf[Nothing].getName)
    logger.setLevel(Level.ALL)
    val handler = new ConsoleHandler
    handler.setLevel(Level.ALL)
    logger.addHandler(handler)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.config(tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.entering(tainted, safe)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.entering("safe", safe, tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.entering(safe, "safe", Array[String](tainted))
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.exiting(safe, tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.exiting(safe, "safe", tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.fine(tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.finer(tainted.trim)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.finest(tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.info(tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.log(Level.INFO, tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.log(Level.INFO, tainted, safe)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.log(Level.INFO, "safe", Array[String](tainted))
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.log(Level.INFO, tainted)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.logp(Level.INFO, tainted, safe, "safe")
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.logp(Level.INFO, safe, "safe", tainted, safe)
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.logp(Level.INFO, "safe", safe.toLowerCase, safe, Array[String](tainted))
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.logrb(Level.INFO, tainted, "safe", "bundle", safe, Array[String](safe))
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.severe(tainted + "safe" + safe)

    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.warning(tainted.replaceAll("\n", "")) // still insecure (CR not replaced)

    // these should not be reported
    logger.fine(safe)
    logger.log(Level.INFO, "safe".toUpperCase, safe + safe)
    logger.logp(Level.INFO, safe, safe, safe, Array[String](safe))
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.logrb(Level.INFO, safe, safe, tainted + "bundle", safe) // bundle name can be tainted

    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.info(tainted.replace('\n', ' ').replace('\r', ' '))
    var encoded = tainted.replace("\r", "").toUpperCase
    encoded = "safe" + encoded.toLowerCase
    // ruleid: scala_inject_rule-CLRFInjectionLogs
    logger.warning(encoded.replace("\n", " (new line)"))
    logger.fine(tainted.replaceAll("[\r\n]+", ""))
  }
}
