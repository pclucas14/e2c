from e2c import * 
from configs import LidarEncoder 
from torch.autograd import Variable
from utils import * 
import torch.optim as optim


LAMBDA = 1e-4 # 100
lambda_adv = .001
print_every = 200
save_every = 2
dump_every = 200
batch_size = 16
ext = 'e2c_lsgan_0.001'
epochs = 500
mse_pretrain = -1

np.random.seed(1)
torch.manual_seed(1)
torch.cuda.manual_seed_all(1)

model = E2C(512*60, 100, 2, config='lidar').cuda()
netD  = LidarEncoder(-1, -1, nz=1).cuda()

#model.decoder.load_state_dict(torch.load(
#    '../../Lidar/models/modelG_lsgan_40.pth'))
# netD.load_state_dict(torch.load(
#     '../../Lidar/models/modelD_lsgan_100.pth'))

print model.encoder
print model.decoder
print netD

dataset = hkl.load('../data/triplets_5_train.hkl')
train_loader = torch.utils.data.DataLoader(dataset, 
                                           batch_size=batch_size,
                                           shuffle=True)
print(len(train_loader))

# print dataset key values to validate preprocessing
ff = np.array([ f for (f,u,n) in dataset])
print ff.shape[0], ff.min(), ff.max(), ff.mean()

optimizerG = optim.Adam(model.parameters(), lr=1e-3) #1e-4
optimizerD = optim.RMSprop(netD.parameters() , lr=1e-4)

for epoch in range(epochs) : 
    model.train()
    data_iter = iter(train_loader)
    gen_iters, disc_iters, iters = 0, 0, 0
    recons, kls, klds, fake_d, fake_g1, fake_g2, real_d = [0] * 7

    while iters < len(train_loader) - 2:
        if epoch > mse_pretrain: 
            disc_iters += 1
            """ update Discriminator Network """
            # overhead
            optimizerD.zero_grad()
            set_grad(netD, True)
            set_grad(model, False)
            
            # fetch data
            x_t, _, x_tp1 = next(data_iter)
            iters += 1

            # to make sure we go through all available samples
            x = x_t if np.random.random() < .5 else x_tp1
            
            # put on GPU
            x = Variable(x.cuda())
             
            model(x, x_t_only=True)
            fake_out = netD(model.x_dec)
            fake_d += fake_out.mean().cpu().data[0]
            loss_fake = torch.mean((fake_out - 0.) ** 2)

            real_out = netD(x)
            real_d += real_out.mean().cpu().data[0]
            loss_real = torch.mean((real_out - 1.) ** 2)

            loss = (loss_real + loss_fake) / 2.
            loss.backward()
            optimizerD.step()

        for _ in range(1): 
            """ update Generator Network """
            optimizerG.zero_grad()
            gen_iters += 1
            set_grad(netD, False)
            set_grad(model, True)

            x_t, u_t, x_tp1 = next(data_iter)
            iters += 1

            # put on GPU
            x_t   = Variable(x_t.cuda())
            u_t   = Variable(u_t.cuda())
            x_tp1 = Variable(x_tp1.cuda())

            # run forward pass
            model(x_t, u_t, x_tp1)
            
            # calculate loss for E2C
            recon_x_t, recon_x_tp1, kld_element, kld, kl = (
                                              compute_loss(model.x_dec, 
                                              model.x_next_pred_dec, 
                                              x_t, 
                                              x_tp1, 
                                              model.Qz, 
                                              model.Qz_next_pred, 
                                              model.Qz_next))

            
            # adversarial loss
            fake_out_x_t = netD(model.x_dec)
            loss_adv = torch.mean((fake_out_x_t - 1.) ** 2) 
            
            fake_g1 += fake_out_x_t.mean().cpu().data[0]
            # fake_g2 += fake_out_x_tp1.mean().cpu().data[0]
            
            # loss_adv.backward(retain_graph=True)

            alpha = 1e-4 if epoch > -1 else 0
            recon_loss = recon_x_t + recon_x_tp1
            loss = recon_loss + LAMBDA * kl.mean() + alpha * kld.mean() + lambda_adv * loss_adv
            loss.mean().backward()
            optimizerG.step()

            recons += recon_loss.cpu().data[0]
            klds += kld.cpu().data[0]
            kls += kl.cpu().data[0]

        if (iters + 1) % print_every <= 1 :  
            print epoch
            print('recon loss : %s   '   % (2*recons  / print_every))
            print('klds loss  : %s   '   % (2*klds    / print_every))
            print('kls loss   : %s   '   % (2*kls     / print_every))
            print('fake_d     : %s   '   % (fake_d  / gen_iters))
            print('fake_g1    : %s   '   % (fake_g1 / gen_iters))
            print('fake_g2    : %s   '   % (fake_g2 / gen_iters))
            print('real_d     : %s   '   % (real_d  / disc_iters))
            recons, kls, klds, fake_d, fake_g1, fake_g2, real_d = [0] * 7
            gen_iters, disc_iters = 0, 0
            monitor_units(kld_element.mul(-.5))

        if (iters + 1) % dump_every <= 1 : 
            save_sample('../clouds/x_dec_%s_%s.hkl'      % (ext, epoch), model.x_dec[0])
            save_sample('../clouds/x_next_dec_%s_%s.hkl' % (ext, epoch), model.x_next_dec[0])
            save_sample('../clouds/x_%s_%s.hkl'          % (ext, epoch), x_t[0])
            save_sample('../clouds/x_next_%s_%s.hkl'     % (ext, epoch), x_tp1[0])
            print 'dumped samples'

    if (epoch + 1) % save_every == 0 : 
        torch.save(model.state_dict(), '../models/' + ext + str(epoch) + '.pth')
        print 'model saved'   

