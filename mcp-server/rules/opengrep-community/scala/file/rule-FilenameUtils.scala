// License: LGPL-3.0 License (c) find-sec-bugs
package file

import org.apache.commons.io.FilenameUtils._
import java.io.File
import java.io.IOException


object FilenameUtils {
  @throws[IOException]
  def main(args: Array[String]): Unit = {
    val maliciousPath = "/test%00/././../../././secret/note.cfg\u0000example.jpg"
    testPath(maliciousPath)
  }

  @throws[IOException]
  private def testPath(maliciousPath: String): Unit = {
    // ruleid: scala_file_rule-FilenameUtils
    val path = normalize(maliciousPath)
    System.out.println("Expected:" + path + " -> Actual:" + canonical(path))
    // ruleid: scala_file_rule-FilenameUtils
    val extension = getExtension(maliciousPath)
    // ruleid: scala_file_rule-FilenameUtils
    System.out.println("Expected:" + extension + " -> Actual:" + getExtension(canonical(path)))
    // ruleid: scala_file_rule-FilenameUtils
    val isExt = isExtension(maliciousPath, "jpg")
    // ruleid: scala_file_rule-FilenameUtils
    System.out.println("Expected:" + isExt + " -> Actual:" + isExtension(canonical(path), "jpg"))
    // ruleid: scala_file_rule-FilenameUtils
    val name = getName(maliciousPath)
    // ruleid: scala_file_rule-FilenameUtils
    System.out.println("Expected:" + name + " -> Actual:" + getName(canonical(name)))
    // ruleid: scala_file_rule-FilenameUtils
    val baseName = getBaseName(maliciousPath)
    // ruleid: scala_file_rule-FilenameUtils
    System.out.println("Expected:" + baseName + " -> Actual:" + getBaseName(canonical(baseName)))
  }

  @throws[IOException]
  private def canonical(path: String) = new File(path).getCanonicalPath
}

