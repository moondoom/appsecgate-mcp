//ruleid: rules_lgpl_oc_other_rule-ios-webview-ignore-ssl
BOOL allowsAnyHTTPSCertificate = YES;
//ruleid: rules_lgpl_oc_other_rule-ios-webview-ignore-ssl
BOOL allowsAnyHTTPSCertificateForHost = YES;

NSURLRequest *requestObj = [NSURLRequest requestWithURL:self.currentURL     cachePolicy:NSURLRequestReturnCacheDataElseLoad timeoutInterval:10.0];
//ruleid: rules_lgpl_oc_other_rule-ios-webview-ignore-ssl
self.loadingUnvalidatedHTTPSPage = YES;
[self.webView loadRequest:requestObj];

@implementation NSURLRequest(OOA)
//ruleid: rules_lgpl_oc_other_rule-ios-webview-ignore-ssl
(BOOL)allowsAnyHTTPSCertificateForHost:(NSString *)host {
    return YES;
}
@end