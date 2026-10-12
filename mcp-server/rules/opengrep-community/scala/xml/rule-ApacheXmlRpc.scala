// License: LGPL-3.0 License (c) find-sec-bugs
package xml

import org.apache.xmlrpc.client.XmlRpcClientConfigImpl
import org.apache.xmlrpc.server.XmlRpcServerConfigImpl

object ApacheXmlRpc {
  def createClientAndServerConfigs(): Unit = {
    val serverConfig = new XmlRpcServerConfigImpl
    val clientConfig = new XmlRpcClientConfigImpl
    val trueValue = true
    // ruleid: scala_xml_rule-ApacheXmlRpc
    clientConfig.setEnabledForExtensions(true) // BAD
    // ruleid: scala_xml_rule-ApacheXmlRpc
    clientConfig.setEnabledForExtensions(trueValue)
    // ruleid: scala_xml_rule-ApacheXmlRpc
    serverConfig.setEnabledForExtensions(true)
    // ruleid: scala_xml_rule-ApacheXmlRpc
    serverConfig.setEnabledForExtensions(trueValue)
    val falseValue = false

    clientConfig.setEnabledForExtensions(false) // GOOD
    clientConfig.setEnabledForExtensions(falseValue)
    serverConfig.setEnabledForExtensions(false)
    serverConfig.setEnabledForExtensions(falseValue)
    val randomFlagForServer = 0 < 0.5
    serverConfig.setEnabledForExtensions(randomFlagForServer)
    val randomFlagForClient = Math.random < 0.5
    clientConfig.setEnabledForExtensions(randomFlagForClient)
  }
}
