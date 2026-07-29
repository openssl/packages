/*
 * A plugin built against an /opt stream, loaded by a host program that is
 * already linked against the distribution's libcrypto (see plugin_host.c).
 *
 * This is the coexistence scenario the packaging exists to support: two OpenSSL
 * library families resident in one process, each reached through its own SONAME
 * and its own symbol versions. Compiled with our pkg-config, so it resolves
 * libcrypto-upstream.so.N via the RUNPATH embedded in Libs.
 */
#include <openssl/crypto.h>
#include <openssl/evp.h>

const char *plugin_version(void)
{
    return OpenSSL_version(OPENSSL_VERSION);
}

int plugin_digest(unsigned char *md, unsigned int *mdlen)
{
    return EVP_Digest("abc", 3, md, mdlen, EVP_sha256(), NULL);
}
