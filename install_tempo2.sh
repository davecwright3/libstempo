#!/bin/bash -e

# get install location
if [ $# -eq 0 ]
	then
		echo 'No install location defined, using' $HOME'/.local/'
		prefix=$HOME/.local/
	else
		prefix=$1
		echo 'Will install in' $prefix
fi

# tempo2 release tag on https://bitbucket.org/psrsoft/tempo2
TEMPO2_TAG=2026.04.1

# make a destination directory for runtime files
export TEMPO2=$prefix/share/tempo2
mkdir -p $TEMPO2

curl -L -O https://bitbucket.org/psrsoft/tempo2/get/${TEMPO2_TAG}.tar.gz
tar zxf ${TEMPO2_TAG}.tar.gz

cd psrsoft-tempo2-*

# remove LT_LIB_DLLOAD from configure.ac
if [[ "$(uname -s)" == "Darwin" ]]; then
  sed -i '' "s/LT_LIB_DLLOAD//g" "configure.ac"
else
  sed -i "s/LT_LIB_DLLOAD//g" "configure.ac"
fi

./bootstrap
# Compile C as gnu17, the default of gcc <= 14. In C23 bool is a keyword, which breaks
# tempo2's jpleph.c `typedef int bool;`; gcc >= 15 defaults to C23 on its own, so
# ac_cv_prog_cc_c23=no (which stops autoconf adding -std=gnu23) is not enough.
# The flag goes in CC, not CFLAGS, because tempo2's build also passes CFLAGS to the C++ compiler.
# glibc < 2.34 keeps dlopen and dlclose in libdl, which LT_LIB_DLLOAD (removed above) would link.
if [[ "$(uname -s)" == "Linux" ]]; then
  extra_libs="-ldl"
fi
./configure --prefix=$prefix ac_cv_prog_cc_c23=no CC="${CC:-gcc} -std=gnu17" LIBS="${LIBS:+$LIBS }${extra_libs:-}"
make
make install
cp -r T2runtime/* $TEMPO2
cd ..

rm -rf psrsoft-tempo2-*
rm -rf ${TEMPO2_TAG}.tar.gz
echo "Set TEMPO2 environment variable to ${TEMPO2} to make things run more smoothly."
