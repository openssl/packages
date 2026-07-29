/*
 * Host program for the coexistence test: linked against the DISTRIBUTION's
 * libcrypto at build time, then dlopens a plugin linked against one of our /opt
 * streams (plugin.c).
 *
 * Both OpenSSL families are live at once. The host's own calls must keep working
 * after the plugin's libcrypto is resident, and each side must report its own
 * version — that is what distinct SONAMEs plus variant-scoped symbol versions
 * buy us. Built without our pkg-config so the system headers are used.
 */
#include <openssl/crypto.h>
#include <openssl/evp.h>

#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef const char *(*plugin_version_fn)(void);
typedef int (*plugin_digest_fn)(unsigned char *, unsigned int *);

static void print_digest(const char *tag, const unsigned char *md, unsigned int mdlen)
{
    unsigned int i;

    printf("%s ", tag);
    for (i = 0; i < mdlen; i++)
        printf("%02x", md[i]);
    printf("\n");
}

int main(int argc, char **argv)
{
    unsigned char md[64];
    unsigned int mdlen = 0;
    plugin_version_fn plugin_version;
    plugin_digest_fn plugin_digest;
    void *handle;

    if (argc < 2) {
        fprintf(stderr, "usage: %s <plugin.so>\n", argv[0]);
        return 2;
    }

    if (EVP_Digest("abc", 3, md, &mdlen, EVP_sha256(), NULL) != 1) {
        fprintf(stderr, "host digest failed\n");
        return 1;
    }
    printf("HOST_VERSION %s\n", OpenSSL_version(OPENSSL_VERSION));
    print_digest("HOST_DIGEST", md, mdlen);

    if ((handle = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL)) == NULL) {
        fprintf(stderr, "dlopen(%s): %s\n", argv[1], dlerror());
        return 1;
    }
    plugin_version = (plugin_version_fn)dlsym(handle, "plugin_version");
    plugin_digest = (plugin_digest_fn)dlsym(handle, "plugin_digest");
    if (plugin_version == NULL || plugin_digest == NULL) {
        fprintf(stderr, "dlsym: %s\n", dlerror());
        return 1;
    }

    memset(md, 0, sizeof(md));
    mdlen = 0;
    if (plugin_digest(md, &mdlen) != 1) {
        fprintf(stderr, "plugin digest failed\n");
        return 1;
    }
    printf("PLUGIN_VERSION %s\n", plugin_version());
    print_digest("PLUGIN_DIGEST", md, mdlen);

    memset(md, 0, sizeof(md));
    mdlen = 0;
    if (EVP_Digest("abc", 3, md, &mdlen, EVP_sha256(), NULL) != 1) {
        fprintf(stderr, "host digest failed after loading the plugin\n");
        return 1;
    }
    print_digest("HOST_DIGEST_AFTER", md, mdlen);
    return 0;
}
