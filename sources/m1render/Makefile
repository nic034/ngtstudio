# Compile le moteur d'emulation m1render (Z80 + YM2610) - Linux / macOS / Windows (MSYS2 ou MinGW) : gcc et g++
# Builds the m1render emulation engine (Z80 + YM2610) - Linux / macOS / Windows (MSYS2 or MinGW): gcc and g++
ifeq ($(OS),Windows_NT)
LIBS = -static -lshell32
endif
all:
	gcc -O2 -c z80/z80.c -o z80.o
	g++ -O2 -std=c++17 -I. m1render.cpp ymfm/ymfm_opn.cpp ymfm/ymfm_adpcm.cpp ymfm/ymfm_ssg.cpp z80.o -o m1render $(LIBS)
clean:
	rm -f z80.o m1render m1render.exe
