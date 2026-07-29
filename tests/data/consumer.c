/*
 * Minimal consumer of an installed stream's -dev package, compiled and run by
 * tests/test_packages.py with `pkg-config --cflags --libs openssl` after
 * sourcing the stream's enable script. Prints the version it was built against
 * and the length of a digest it computed.
 */
#include <openssl/evp.h>
#include <openssl/opensslv.h>

#include <stdio.h>

int main(void)
{
    unsigned char md[32];
    size_t mdlen = 0;

    EVP_Q_digest(NULL, "SHA256", NULL, "abc", 3, md, &mdlen);
    printf("%s %zu\n", OpenSSL_version(OPENSSL_VERSION_STRING), mdlen);
    return 0;
}
