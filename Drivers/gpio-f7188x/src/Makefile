ifneq ($(KERNELRELEASE),)
obj-m	+= gpio-f7188x.o
else
KDIR ?= /lib/modules/$(shell uname -r)/build
all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
endif