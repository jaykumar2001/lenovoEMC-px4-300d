#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/fs.h>
#include <linux/types.h>
#include <linux/uaccess.h>
#include <linux/delay.h>
#include <linux/miscdevice.h>
#include <linux/io.h>
#include "ums8485md.h"
#include "ilogo.h"

#define DRV_NAME	"lcm"
#define STATIC_LCM_MINOR	1
#define LCM_MINOR	128

/* ICH9 GPIO register offsets from GPIOBASE */
#define ICH9_GPIO_USE_SEL	0x000
#define ICH9_GP_IO_SEL		0x004
#define ICH9_GP_LVL		0x00C
#define ICH9_GPIOBASE_REG	0x48

/* LCD pins as ICH9 GPIO bitmasks */
#define LCD_BIT_SI		(1 << 6)
#define LCD_BIT_SCL		(1 << 7)
#define LCD_BIT_RS		(1 << 16)
#define LCD_BIT_A0		(1 << 19)
#define LCD_BIT_CS1		(1 << 21)
#define LCD_ALL_PINS		(LCD_BIT_SI | LCD_BIT_SCL | LCD_BIT_RS | \
				 LCD_BIT_A0 | LCD_BIT_CS1)

enum lcm_a0_state {
	LCM_CONTROL_DATA = 0,
	LCM_DISPLAY_DATA,
};

static long lcm_ioctl(struct file *file, unsigned int cmd, unsigned long arg);

static int lcm_initdata[] = { 0xa0, 0x2f, 0xa2, 0xc8, 0x27, 0x81, 0x17, 0xaf };

static u32 gpio_base;

static inline void lcd_pin_set(u32 pin_mask, int value)
{
	u32 lvl = inl(gpio_base + ICH9_GP_LVL);

	if (value)
		lvl |= pin_mask;
	else
		lvl &= ~pin_mask;
	outl(lvl, gpio_base + ICH9_GP_LVL);
}

static int lcm_open(struct inode *inode, struct file *file)
{
	return 0;
}

static void write_lcm_data(int type, unsigned char data)
{
	int i;

	lcd_pin_set(LCD_BIT_CS1, 0);
	lcd_pin_set(LCD_BIT_A0, type ? LCM_DISPLAY_DATA : LCM_CONTROL_DATA);

	for (i = 0; i < 8; i++) {
		lcd_pin_set(LCD_BIT_SCL, 0);
		lcd_pin_set(LCD_BIT_SI, (data & 0x80) ? 1 : 0);
		lcd_pin_set(LCD_BIT_SCL, 1);
		data <<= 1;
	}
	lcd_pin_set(LCD_BIT_CS1, 1);
}

static void reload_logo(void)
{
	int i, j , col;

	col = 0;
	for(i = 0; i < 8; i++) {
		write_lcm_data(LCM_CONTROL_DATA, (0x0f & col));
		write_lcm_data(LCM_CONTROL_DATA, (0x10 | (0x0f & col >> 4)));
		write_lcm_data(LCM_CONTROL_DATA, (0xb0 + i));

		for(j = 0; j < 128; j++) {
			write_lcm_data(LCM_DISPLAY_DATA, (j%8==0));
//			write_lcm_data(LCM_DISPLAY_DATA, ilogo[j+128*i]);
		}
	}
}

static int write_lcm(lcm_member_t buf)
{
	int i;
		write_lcm_data(LCM_CONTROL_DATA, (0xb0 + buf.page));
		write_lcm_data(LCM_CONTROL_DATA, (0x0f & buf.column));
		write_lcm_data(LCM_CONTROL_DATA, (0x10 | (0x0f & buf.column >> 4)));
	if(buf.ctrl != WIX_LCM_CMD_RESET) {
	for(i = 0; i < buf.size; i++)
		write_lcm_data(LCM_DISPLAY_DATA, buf.data[i]);
	}

	switch(buf.ctrl) {
		case WIX_LCM_CMD_PON :
			write_lcm_data(LCM_CONTROL_DATA, 0xaf);
			break;
		case WIX_LCM_CMD_POFF :
			write_lcm_data(LCM_CONTROL_DATA, 0xae);
			break;
		case WIX_LCM_CMD_RESET :
			for (i = 0; i < ARRAY_SIZE(lcm_initdata); i++) {
				write_lcm_data(LCM_CONTROL_DATA, lcm_initdata[i]);
			}
			reload_logo();
			break;
		case WIX_LCM_CMD_DISP_NORMAL :
			write_lcm_data(LCM_CONTROL_DATA, 0xa6);
			break;
		case WIX_LCM_CMD_DISP_REVERSE :
			write_lcm_data(LCM_CONTROL_DATA, 0xa7);
			break;
		case WIX_LCM_CMD_ENTIRE_DISP_ON :
			write_lcm_data(LCM_CONTROL_DATA, 0xa5);
			break;
		case WIX_LCM_CMD_ENTIRE_DISP_OFF :
			write_lcm_data(LCM_CONTROL_DATA, 0xa4);
			break;
		case WIX_LCM_CMD_ADC_SELECT_NORMAL :
			write_lcm_data(LCM_CONTROL_DATA, 0xa0);
			break;
		case WIX_LCM_CMD_ADC_SELECT_REVERSE :
			write_lcm_data(LCM_CONTROL_DATA, 0xa1);
			break;
		case WIX_LCM_CMD_OUTPUT_NORMAL :
			write_lcm_data(LCM_CONTROL_DATA, 0xc0);
			break;
		case WIX_LCM_CMD_OUTPUT_REVERSE :
			write_lcm_data(LCM_CONTROL_DATA, 0xc8);
			break;
		case WIX_LCM_CMD_WRITE_DATA:
			break;
		default :
			pr_info("[%s] Unknow ctrl command. \n", __func__);
			break;
	}
	return 0;
}

#ifdef UMS_DEBUG
static void data_dump(lcm_member_t buf)
{
	int i;

	pr_info("-------[%s] data dump -------\n", __func__);
	pr_info("ctrl : %d\n", buf.ctrl);
	pr_info("page : %d\n", buf.page);
	pr_info("column : %d\n", buf.column);
	pr_info("size : %d\n", buf.size);

	for(i = 0; i < 128; i++) {
		printk("%4d", buf.data[i]);
		if((i % 16) == 0)
			printk("\n");
	}
}
#endif

static int data_check(lcm_member_t buf)
{
	if((buf.page < 0 ) || (buf.page > 7)) {
		return -1;
	}
	if((buf.column < 0 ) || (buf.column > 127))
		return -1;
	return 0;
}

static long lcm_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	lcm_member_t info;

	if (copy_from_user(&info, (lcm_member_t *) arg, sizeof(lcm_member_t)))
	{
		pr_err("[%s]->[%s] can't opy data from the user space!\n", DRV_NAME, __func__);
		return -EFAULT;
	}

	if(data_check(info))
		return -EFAULT;

#ifdef UMS_DEBUG
	data_dump(info);
#endif
	switch(cmd) {
		case IOCTL_DISPLAY_COMMAND :
			write_lcm(info);
			break;
		default :
			pr_info("[%s]->[%s] Unknown IOCTL command\n", DRV_NAME, __func__);
			break;
	};

	return 0;
}

static int lcm_close(struct inode * inode, struct file * file)
{
	return 0;
}

static struct file_operations lcm_fops = {
	.owner	= THIS_MODULE,
	.unlocked_ioctl	= lcm_ioctl,
	.compat_ioctl	= lcm_ioctl,
	.open		= lcm_open,
	.release	= lcm_close
};

static struct miscdevice lcm_dev = {

#if STATIC_LCM_MINOR
	LCM_MINOR,
#else
	MISC_DYNAMIC_MINOR,
#endif
	"lcm",
	&lcm_fops,
};

static int lcm_gpio_init(void)
{
	struct pci_dev *lpc_dev;
	u32 base_cfg, use_sel, io_sel;
	int i;

	lpc_dev = pci_get_device(PCI_VENDOR_ID_INTEL, 0x2916, NULL);
	if (!lpc_dev) {
		pr_err("ICH9 LPC bridge not found\n");
		return -ENODEV;
	}

	pci_read_config_dword(lpc_dev, ICH9_GPIOBASE_REG, &base_cfg);
	pci_dev_put(lpc_dev);

	gpio_base = base_cfg & 0xFFC0;
	if (!gpio_base) {
		pr_err("ICH9 GPIOBASE not configured\n");
		return -ENODEV;
	}

	pr_info("ICH9 GPIOBASE = 0x%04x\n", gpio_base);

	/* Configure all LCD pins as GPIO output */
	use_sel = inl(gpio_base + ICH9_GPIO_USE_SEL);
	outl(use_sel | LCD_ALL_PINS, gpio_base + ICH9_GPIO_USE_SEL);

	io_sel = inl(gpio_base + ICH9_GP_IO_SEL);
	outl(io_sel & ~LCD_ALL_PINS, gpio_base + ICH9_GP_IO_SEL);

	/* All pins low, then RS reset pulse */
	lcd_pin_set(LCD_ALL_PINS, 0);
	lcd_pin_set(LCD_BIT_RS, 0);
	mdelay(200);
	lcd_pin_set(LCD_BIT_RS, 1);
	mdelay(200);
	lcd_pin_set(LCD_BIT_CS1, 1);
	lcd_pin_set(LCD_BIT_SCL, 1);

	for (i = 0; i < ARRAY_SIZE(lcm_initdata); i++)
		write_lcm_data(LCM_CONTROL_DATA, lcm_initdata[i]);

	reload_logo();
	return 0;
}

static int __init lcm_init(void)
{
	int ret;

	ret = lcm_gpio_init();
	if (ret)
		return ret;

	ret = misc_register(&lcm_dev);
	if (ret) {
		pr_err("could not register the lcm driver\n");
		return ret;
	}

	pr_info("lcm driver registered (ICH9 GPIO)\n");
	return 0;
}

static void __exit lcm_exit(void)
{
	misc_deregister(&lcm_dev);
}

MODULE_DESCRIPTION ("LCM Driver");
MODULE_LICENSE("GPL");

module_init(lcm_init);
module_exit(lcm_exit);
