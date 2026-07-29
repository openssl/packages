/*
 * Load two independent libcrypto objects into one process and use both.
 *
 * Built and run by tests/test_coexistence.py. Each argument is a path to a
 * libcrypto shared object; every one is dlopen'd with RTLD_GLOBAL, which is the
 * harsh case: all exported symbols land in the global scope, so two objects
 * sharing a SONAME or a symbol version would collide here.
 *
 * Only functions present in every OpenSSL from 1.1.1 onwards are used, because
 * one of the two objects is the distribution's and the oldest target ships
 * 1.1.1. Nothing is included from either OpenSSL's headers.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

typedef const char *(*version_fn)(int);
typedef const void *(*md_fn)(void);
typedef int (*digest_fn)(const void *data, size_t count, unsigned char *md,
                         unsigned int *size, const void *type, void *impl);

/* OpenSSL_version() selector for the full version banner; 0 in every release
 * that has the function. */
#define OSSL_VERSION_BANNER 0

static int probe(const char *path)
{
    void *handle;
    version_fn version;
    md_fn sha256;
    digest_fn digest;
    unsigned char md[64];
    unsigned int mdlen = 0, i;

    if ((handle = dlopen(path, RTLD_NOW | RTLD_GLOBAL)) == NULL) {
        fprintf(stderr, "dlopen(%s): %s\n", path, dlerror());
        return 1;
    }

    version = (version_fn)dlsym(handle, "OpenSSL_version");
    sha256 = (md_fn)dlsym(handle, "EVP_sha256");
    digest = (digest_fn)dlsym(handle, "EVP_Digest");
    if (version == NULL || sha256 == NULL || digest == NULL) {
        fprintf(stderr, "dlsym(%s): missing expected symbol\n", path);
        return 1;
    }

    if (digest("abc", 3, md, &mdlen, sha256(), NULL) != 1 || mdlen != 32) {
        fprintf(stderr, "EVP_Digest failed in %s\n", path);
        return 1;
    }

    printf("VERSION %s\n", version(OSSL_VERSION_BANNER));
    printf("DIGEST ");
    for (i = 0; i < mdlen; i++)
        printf("%02x", md[i]);
    printf("\n");
    return 0;
}

/*
 * Report every mapped file whose name mentions libcrypto. The test uses this to
 * confirm both objects are resident simultaneously rather than one satisfying
 * the other's load. In a maps line the first '/' begins the pathname.
 */
static void report_mapped(void)
{
    char line[4096];
    FILE *maps;

    if ((maps = fopen("/proc/self/maps", "r")) == NULL)
        return;
    while (fgets(line, sizeof(line), maps) != NULL) {
        char *path = strchr(line, '/');

        if (path != NULL && strstr(path, "libcrypto") != NULL)
            printf("MAPPED %s", path);
    }
    fclose(maps);
}

int main(int argc, char **argv)
{
    int i;

    if (argc < 3) {
        fprintf(stderr, "usage: %s <libcrypto> <libcrypto> [...]\n", argv[0]);
        return 2;
    }
    for (i = 1; i < argc; i++)
        if (probe(argv[i]) != 0)
            return 1;
    report_mapped();
    return 0;
}
