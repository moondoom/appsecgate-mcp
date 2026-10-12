// License: LGPL-3.0 License (c) find-sec-bugs
package perm

import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.attribute.PosixFilePermission
import java.util.HashSet
import scala.collection.mutable.HashSet
import scala.jdk.CollectionConverters.SetHasAsJava

class OverlyPermissiveFilePermissionObj {
  @throws[IOException]
  def dangerObjOriented(path: Path): Unit = {
    val perms = new java.util.HashSet[PosixFilePermission]()
    perms.add(PosixFilePermission.OWNER_READ)
    perms.add(PosixFilePermission.OWNER_WRITE)
    perms.add(PosixFilePermission.OWNER_EXECUTE)
    perms.add(PosixFilePermission.GROUP_READ)
    perms.add(PosixFilePermission.GROUP_WRITE)
    perms.add(PosixFilePermission.GROUP_EXECUTE)
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms.add(PosixFilePermission.OTHERS_READ)
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms.add(PosixFilePermission.OTHERS_WRITE)
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms.add(PosixFilePermission.OTHERS_EXECUTE)
    Files.setPosixFilePermissions(path, perms)
  }

  @throws[IOException]
  def dangerObjOriented2(path: Path, perms: java.util.Set[PosixFilePermission]): Unit = {
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms.add(PosixFilePermission.OTHERS_READ)
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms.add(PosixFilePermission.OTHERS_WRITE)
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms.add(PosixFilePermission.OTHERS_EXECUTE)
    Files.setPosixFilePermissions(path, perms)
  }

  @throws[IOException]
  def dangerObjOriented3(path: Path): Unit = {
    var perms: scala.collection.immutable.HashSet[PosixFilePermission] = scala.collection.immutable.HashSet()
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms = perms + PosixFilePermission.OTHERS_READ
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms = perms + PosixFilePermission.OTHERS_READ
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms = perms + PosixFilePermission.OTHERS_WRITE
    // ruleid: scala_perm_rule-OverlyPermissiveFilePermissionObj
    perms = perms + PosixFilePermission.OTHERS_EXECUTE
    Files.setPosixFilePermissions(path, perms.asJava)
  }

  @throws[IOException]
  def okObjOriented(path: Path): Unit = {
    val perms = new java.util.HashSet[PosixFilePermission]()
    perms.add(PosixFilePermission.OWNER_READ)
    perms.add(PosixFilePermission.OWNER_WRITE)
    perms.add(PosixFilePermission.OWNER_EXECUTE)
    perms.add(PosixFilePermission.GROUP_READ)
    perms.add(PosixFilePermission.GROUP_WRITE)
    perms.add(PosixFilePermission.GROUP_EXECUTE)
    Files.setPosixFilePermissions(path, perms)
  }
}
