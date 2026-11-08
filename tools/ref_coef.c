/*
 * Reference helper for cross-validating the pure-Python jphs codec.
 *
 *   ref_coef dump   in.jpg out.bin
 *   ref_coef trans  in.jpg out.jpg
 *
 * "dump" writes the decoded coefficient arrays (including libjpeg's padded
 * edge blocks) as a small binary header followed by little-endian int16
 * coefficients in natural order.  "trans" performs the same
 * read_coefficients / copy_critical_parameters / write_coefficients dance
 * that jphide uses, with optimize_coding enabled.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "jpeglib.h"

static void read_file(const char *name, unsigned char **data, long *size)
{
  FILE *f = fopen(name, "rb");
  long n;

  if (!f) { perror(name); exit(2); }
  if (fseek(f, 0, SEEK_END) || (n = ftell(f)) < 0 || fseek(f, 0, SEEK_SET))
  { perror(name); exit(2); }
  *data = (unsigned char *) malloc(n ? n : 1);
  if (!*data) { fprintf(stderr, "out of memory\n"); exit(2); }
  if (n && fread(*data, 1, n, f) != (size_t) n)
  { perror(name); exit(2); }
  fclose(f);
  *size = n;
}

static void write_file(const char *name, const unsigned char *data, long size)
{
  FILE *f = fopen(name, "wb");

  if (!f) { perror(name); exit(2); }
  if (size && fwrite(data, 1, size, f) != (size_t) size)
  { perror(name); exit(2); }
  fclose(f);
}

static void put16(FILE *f, int v)
{
  fputc(v & 0xFF, f);
  fputc((v >> 8) & 0xFF, f);
}

static void put32(FILE *f, long v)
{
  fputc(v & 0xFF, f);
  fputc((v >> 8) & 0xFF, f);
  fputc((v >> 16) & 0xFF, f);
  fputc((v >> 24) & 0xFF, f);
}

static void do_dump(struct jpeg_decompress_struct *src, const char *outname)
{
  jvirt_barray_ptr *arrays = jpeg_read_coefficients(src);
  FILE *f = fopen(outname, "wb");
  int ci;

  if (!f) { perror(outname); exit(2); }
  fputs("JCOEF1\n", f);
  put32(f, src->image_width);
  put32(f, src->image_height);
  put32(f, src->num_components);
  put32(f, src->data_precision);
  put32(f, src->jpeg_color_space);
  put32(f, src->saw_JFIF_marker);
  put32(f, src->JFIF_major_version);
  put32(f, src->JFIF_minor_version);
  put32(f, src->density_unit);
  put32(f, src->X_density);
  put32(f, src->Y_density);
  put32(f, src->saw_Adobe_marker);
  put32(f, src->Adobe_transform);

  for (ci = 0; ci < src->num_components; ci++) {
    jpeg_component_info *c = &src->comp_info[ci];
    put32(f, c->component_id);
    put32(f, c->h_samp_factor);
    put32(f, c->v_samp_factor);
    put32(f, c->quant_tbl_no);
    put32(f, c->width_in_blocks);
    put32(f, c->height_in_blocks);
  }

  for (ci = 0; ci < src->num_components; ci++) {
    jpeg_component_info *c = &src->comp_info[ci];
    long padded_w = ((long) c->width_in_blocks + c->h_samp_factor - 1)
                    / c->h_samp_factor * c->h_samp_factor;
    long padded_h = ((long) c->height_in_blocks + c->v_samp_factor - 1)
                    / c->v_samp_factor * c->v_samp_factor;
    JDIMENSION row;

    for (row = 0; row < padded_h; row++) {
      JBLOCKARRAY buf = (*src->mem->access_virt_barray)
        ((j_common_ptr) src, arrays[ci], row, 1, FALSE);
      long bx;
      for (bx = 0; bx < padded_w; bx++) {
        int k;
        for (k = 0; k < DCTSIZE2; k++)
          put16(f, buf[0][bx][k]);
      }
    }
  }
  fclose(f);
}

static void do_trans(struct jpeg_decompress_struct *src, const char *outname)
{
  struct jpeg_compress_struct dst;
  struct jpeg_error_mgr jerr;
  jvirt_barray_ptr *arrays = jpeg_read_coefficients(src);
  FILE *f = fopen(outname, "wb");

  if (!f) { perror(outname); exit(2); }
  jpeg_create_compress(&dst);
  dst.err = jpeg_std_error(&jerr);
  jpeg_stdio_dest(&dst, f);
  jpeg_copy_critical_parameters(src, &dst);
  dst.optimize_coding = TRUE;
  jpeg_write_coefficients(&dst, arrays);
  jpeg_finish_compress(&dst);
  jpeg_destroy_compress(&dst);
  fclose(f);
}

int main(int argc, char **argv)
{
  struct jpeg_decompress_struct src;
  struct jpeg_error_mgr jerr;
  unsigned char *data;
  long size;
  struct jpeg_source_mgr *srcmgr;
  int dump;

  if (argc != 4 || (strcmp(argv[1], "dump") && strcmp(argv[1], "trans")))
  {
    fprintf(stderr, "usage: %s dump|trans in.jpg out\n", argv[0]);
    return 2;
  }
  dump = !strcmp(argv[1], "dump");
  read_file(argv[2], &data, &size);

  jpeg_create_decompress(&src);
  src.err = jpeg_std_error(&jerr);
  jpeg_mem_src(&src, data, size);
  srcmgr = src.src;
  (void) srcmgr;
  jpeg_read_header(&src, TRUE);

  if (dump)
    do_dump(&src, argv[3]);
  else
    do_trans(&src, argv[3]);

  jpeg_destroy_decompress(&src);
  free(data);
  return 0;
}
