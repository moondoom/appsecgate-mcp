let context = LAContext()

// ok: rules_lgpl_swift_other_rule-ios-biometric-acl
if context.biometryType == .biometryAny {
    print("Biometric authentication is available")
}

var accessControl: SecAccessControl?

// ok: rules_lgpl_swift_other_rule-ios-biometric-acl
let flags: SecAccessControlCreateFlags = [.biometryAny, .userPresence]

// ruleid: rules_lgpl_swift_other_rule-ios-biometric-acl
let status = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .biometryAny, &accessControl)

// ok: rules_lgpl_swift_other_rule-ios-biometric-acl
let status2 = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .biometryCurrentSet, &accessControl)

// ruleid: rules_lgpl_swift_other_rule-ios-biometric-acl
let insecureFlags: SecAccessControlCreateFlags = .biometryAny
let status3 = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, insecureFlags, &accessControl)

// ruleid: rules_lgpl_swift_other_rule-ios-biometric-acl
let insecureFlagsArray: SecAccessControlCreateFlags = [.userPresence, .privateKeyUsage]
let status4 = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, insecureFlagsArray, &accessControl)

// ok: rules_lgpl_swift_other_rule-ios-biometric-acl
let secureFlags: SecAccessControlCreateFlags = .biometryCurrentSet
let status5 = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, secureFlags, &accessControl)

// ruleid: rules_lgpl_swift_other_rule-ios-biometric-acl
let status6 = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .userPresence, &accessControl)

// ruleid: rules_lgpl_swift_other_rule-ios-biometric-acl
let status7 = SecAccessControlCreateWithFlags(kCFAllocatorDefault, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .touchIDAny, &accessControl)