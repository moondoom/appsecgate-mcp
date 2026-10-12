// License: LGPL-3.0 License (c) find-sec-bugs
package strings

import java.net.IDN
import java.net.URI
import java.text.Normalizer

class ImproperUnicode {
  def dangerToUpperEquals(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    s.toUpperCase().equals("TEST")
  }

  def dangerToUpperEqualIgnoreCase(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    s.toUpperCase().equalsIgnoreCase("TEST")
  }

  def dangerToUpperIndexOf(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    s.toUpperCase().indexOf("T")
  }

  def dangerToLowerEquals(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    s.toLowerCase().equals("test")
  }

  def dangerToLowerEqualIgnoreCase(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    s.toLowerCase().equalsIgnoreCase("test")
  }

  def dangerToLowerIndexOf(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    s.toLowerCase().indexOf("t")
  }

  def dangerURI(uri: URI) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    uri.toASCIIString()
  }

  def dangerIDN(input: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    IDN.toASCII(input)
  }

  def dangerNormalize(s: String) = {
    // ruleid: scala_strings_rule-ImproperUnicode
    Normalizer.normalize(s.toUpperCase, Normalizer.Form.NFKC).equals("ADMIN")
  }
}
